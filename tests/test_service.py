import json
from datetime import date
from pathlib import Path

import httpx
from typer.testing import CliRunner

from forge_astra.cli import app
from forge_astra.config import Settings
from forge_astra.http import JsonHTTP
from forge_astra.service import Application
from forge_astra.storage import Store
from forge_astra.upstream import CARDS


def test_discovery_generation_exports_and_retry_survive_reopening(corpus, tmp_path):
    # Real indexed support cards keep deck validation in the end-to-end path.
    support = [f"Training Relic {i}" for i in range(7)]
    for i, name in enumerate(support):
        (corpus.root / CARDS / f"relic_{i}.txt").write_text(
            f"Name:{name}\nManaCost:1\nTypes:Artifact\n"
            "A:AB$ Draw | NumCards$ 1 | Cost$ 2 T\nOracle:Draw a card.\n"
        )
    corpus.index(corpus.root, "b" * 40)
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        llm_base_url="https://model.example.test/v1",
        llm_model="contract-model",
        llm_api_key="never-export-this-test-key",
        langfuse_enabled=False,
    )
    application = Application(settings)
    application.corpus.close()
    application.corpus = corpus
    day = date(2026, 9, 5)

    def card(identifier, set_code):
        name = f"Trial Flame {identifier}"
        return {
            "id": identifier,
            "name": name,
            "set": set_code,
            "released_at": "2026-10-01",
            "mana_cost": "{R}",
            "type_line": "Instant",
            "color_identity": ["R"],
            "oracle_text": f"{name} deals 3 damage to any target.",
        }

    discovered = [card("baseline", "old")]

    def scryfall(request):
        data = discovered if "date>=" in request.url.params["q"] else [{"name": "Lightning Bolt"}]
        return httpx.Response(200, json={"data": data, "has_more": False})

    failing = {"retry"}
    calls = []

    def model(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        context, schema = payload["context"], payload["schema"]["title"]
        calls.append((context["card"]["id"], schema))
        if context["card"]["id"] in failing:
            raise httpx.ReadTimeout("temporary model failure", request=request)
        if schema == "Plan":
            evidence = next(e for e in context["evidence"] if e["name"] == "Lightning Bolt")
            result = {
                "clauses": [
                    {
                        "clause_id": clause["id"],
                        "explanation": "Reuse the upstream damage ability",
                        "citations": [{"evidence_id": evidence["id"], "quote": "SP$ DealDamage"}],
                        "needs_engine": False,
                    }
                    for clause in context["clauses"]
                ],
                "mechanics": [],
            }
        elif schema == "Draft":
            result = {
                "faces": [{"lines": ["A:SP$ DealDamage | ValidTgts$ Any | NumDmg$ 3"]}],
                "support_cards": [
                    {"name": name, "count": 4, "purpose": "Draw cards"} for name in support
                ],
                "test_plan": ["Deal exactly three damage to a 4/4; it survives before cleanup."],
                "lessons": ["The damage amount is expressed in NumDmg."],
            }
        else:
            assert schema == "Review"
            result = {
                "verdict": "pass",
                "clauses": [
                    {"clause_id": clause["id"], "implemented": True, "explanation": "Three damage"}
                    for clause in context["clauses"]
                ],
                "issues": [],
                "new_mechanics": [],
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]
            },
        )

    application.scryfall.http.close()
    application.scryfall.http = JsonHTTP(
        "https://api.scryfall.com", transport=httpx.MockTransport(scryfall)
    )
    application.llm.http.close()
    application.llm.http = JsonHTTP(settings.llm_base_url, transport=httpx.MockTransport(model))
    try:
        assert application.discover(day) == {"new": 0, "changed": 0, "baseline": 1}
        discovered.extend([card("one", "seta"), card("two", "setb"), card("retry", "seta")])
        assert application.discover(day)["new"] == 3
        first = application.process(day)
        assert {c["name"]: c["status"] for c in first["cards"]} == {
            "Trial Flame one": "draft",
            "Trial Flame two": "draft",
            "Trial Flame retry": "error",
        }
        for set_code in ("seta", "setb"):
            manifest = json.loads((Path(first["path"]) / set_code / "manifest.json").read_text())
            assert {entry["set_code"] for entry in manifest} == {set_code}
        for entry in first["cards"]:
            report = Path(entry["report"]).read_text()
            assert settings.llm_api_key.get_secret_value() not in report
            assert json.loads(report)["gameplay_tested"] is False
            if entry["status"] == "draft":
                deck = Path(entry["deck"]).read_text()
                assert f"8 {entry['name']}" in deck
                assert (
                    sum(int(line.split()[0]) for line in deck.splitlines() if line[:1].isdigit())
                    == 60
                )
                assert len(json.loads(report)["model_calls"]) == 3
            else:
                assert "script" not in entry and "deck" not in entry
        application.store.close()
        application.store = Store(settings.db_path)
        assert [row["key"] for row in application.store.queue(20)] == ["retry"]
        notes = application.store.knowledge("damage")["lessons"]
        assert len(notes) == 2 and all(note["status"] == "unverified" for note in notes)
        first_calls = len(calls)
        failing.clear()
        second = application.process(day)
        assert len(second["cards"]) == 1 and second["cards"][0]["status"] == "draft"
        assert all(identifier == "retry" for identifier, _ in calls[first_calls:])
        assert application.store.queue(20) == []
        assert Path(first["path"]).exists() and first["path"] != second["path"]
        # Feedback uses the same real storage path, then enters the next plan.
        env_file = tmp_path / "cli.env"
        env_file.write_text(f"ASTRA_DATA_DIR={settings.data_dir}\n")
        runner = CliRunner()
        feedback = runner.invoke(
            app,
            [
                "--env-file",
                str(env_file),
                "feedback",
                "one",
                "Verified that a 4/4 survives until cleanup.",
                "--outcome",
                "reviewed",
                "--retry-card",
            ],
        )
        assert feedback.exit_code == 0, feedback.output
        third = application.process(day)
        assert [entry["name"] for entry in third["cards"]] == ["Trial Flame one"]
        report = json.loads(Path(third["cards"][0]["report"]).read_text())
        assert any(note["status"] == "reviewed" for note in report["knowledge"]["lessons"])
        exported = tmp_path / "learned.md"
        result = runner.invoke(
            app, ["--env-file", str(env_file), "export-knowledge", str(exported)]
        )
        assert result.exit_code == 0, result.output
        text = exported.read_text()
        assert "Verified that a 4/4 survives until cleanup." in text
        assert "explicit_feedback" in text and "(unverified)" in text
    finally:
        application.close()
