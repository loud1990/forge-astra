import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_workflow import FakeGitHub, FakeLLM, FakeScryfall, draft, pool, renamed_bolt

from forge_astra.config import Settings
from forge_astra.corpus import Corpus
from forge_astra.evaluation import evaluate_cards
from forge_astra.observability import Telemetry
from forge_astra.scripting import assemble
from forge_astra.storage import Store
from forge_astra.upstream import CARDS
from forge_astra.workflow import Workflow


def test_holdout_filters_all_retrieval_paths_and_restores_after_failure(corpus):
    bolt = corpus.named("Lightning Bolt")[0]
    bird = corpus.named("Bird")[0]
    with corpus.db:
        corpus.add("other-bird", "script", "Other Bird", "Flying", "K:Flying", "other.txt")
    before = corpus.db.execute("SELECT count(*) FROM evidence").fetchone()[0]
    with pytest.raises(RuntimeError, match="interrupted"):
        with corpus.withhold_cards(["lightning bolt", "Bird"]) as hidden:
            assert {e["id"] for e in hidden} == {bolt["id"], bird["id"]}
            assert corpus.named("Lightning Bolt") == []
            assert corpus.get(bolt["id"]) is None
            assert corpus.search("deals damage") == []
            assert corpus.search("Flying", limit=1)[0]["name"] == "Other Bird"
            assert corpus.mechanic_examples("Flying", limit=1)[0]["name"] == "Other Bird"
            with corpus.withhold_cards(["Other Bird"]):
                assert corpus.mechanic_examples("Flying") == []
                assert not corpus.has_keyword_line("K:Flying")
            assert corpus.has_keyword_line("K:Flying")
            # A separate connection still sees the complete persistent index.
            other = Corpus(Path(corpus.db.execute("PRAGMA database_list").fetchone()[2]))
            try:
                assert other.named("Lightning Bolt")
            finally:
                other.close()
            raise RuntimeError("interrupted")
    assert corpus.get(bolt["id"]) == bolt
    assert corpus.named("Bird") == [bird]
    assert corpus.db.execute("SELECT count(*) FROM evidence").fetchone()[0] == before


@pytest.mark.parametrize("name", ["Day // Night", "Day", "night"])
def test_holdout_of_either_face_hides_entire_script(corpus, name):
    with corpus.db:
        corpus.add("faces", "script", "Day // Night", "Flying", "K:Flying", "faces.txt")
    with corpus.withhold_cards([name]):
        for lookup in ("Day // Night", "Day", "Night"):
            assert corpus.named(lookup) == []
        assert corpus.get("faces") is None
        assert all(e["id"] != "faces" for e in corpus.search("Flying"))
    assert corpus.named("Night")[0]["id"] == "faces"


def test_real_evaluation_holds_out_all_targets_and_keeps_production_state(
    corpus, tmp_path, monkeypatch
):
    cards = [renamed_bolt("abc"), renamed_bolt("def")]
    cards[1].name = cards[1].faces[0].name = "Second Ember Test"
    cards[1].faces[0].oracle_text = "Second Ember Test deals 3 damage to any target."
    for i, card in enumerate(cards):
        (corpus.root / CARDS / f"target_{i}.txt").write_text(
            assemble(card, draft()) + "\n# DO_NOT_LEAK_TARGET_SCRIPT\n"
        )
    corpus.index(corpus.root, "b" * 40)
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "out",
        langfuse_enabled=False,
    )
    store = Store(settings.db_path)
    store.enqueue(cards[0], cards[0].released_at)
    llm = FakeLLM()
    llm.history = []
    original_ask = llm.ask
    contexts = []

    def ask(task, context, schema, review=False):
        contexts.append(context)
        serialized = json.dumps(context)
        assert "DO_NOT_LEAK_TARGET_SCRIPT" not in serialized
        assert "target_0.txt" not in serialized and "target_1.txt" not in serialized
        return original_ask(task, context, schema, review)

    llm.ask = ask
    monkeypatch.setattr(Workflow, "support_pool", lambda self, card: pool())
    application = SimpleNamespace(
        settings=settings,
        corpus=corpus,
        scryfall=FakeScryfall(),
        github=FakeGitHub(),
        llm=llm,
        telemetry=Telemetry(settings),
    )
    workflow = Workflow(settings, store, corpus, application.scryfall, application.github, llm)
    try:
        assert (
            workflow.research({"card": cards[0].model_dump(mode="json")})["status"]
            == "already_upstream"
        )
        before = [dict(r) for r in store.db.execute("SELECT * FROM cards")]
        summary = evaluate_cards(application, cards)
        assert summary["mode"] == "held_out_cards"
        assert summary["passed"] == summary["total"] == 2
        assert len(summary["withheld_scripts"]) == 2
        assert llm.calls == ["Plan", "Draft", "Review"] * 2
        assert len(contexts) == 6
        for result in summary["results"]:
            report = json.loads(Path(result["artifact"]["report"]).read_text())
            assert report["discovery"]["withheld_scripts"] == summary["withheld_scripts"]
            assert report["gameplay_tested"] is False
            assert report["status"] == "draft"
        for card in cards:
            assert corpus.named(card.name)
        assert [dict(r) for r in store.db.execute("SELECT * FROM cards")] == before
        assert store.db.execute("SELECT count(*) FROM lessons").fetchone()[0] == 0
    finally:
        store.close()


def test_sample_rejects_empty_and_duplicate_inputs():
    card = renamed_bolt()
    with pytest.raises(ValueError, match="No cards"):
        evaluate_cards(None, [])
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_cards(None, [card, card])
