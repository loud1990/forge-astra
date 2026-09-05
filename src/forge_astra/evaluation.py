import json
import logging
import re
from datetime import datetime
from importlib.resources import files
from uuid import uuid4

from forge_astra.artifacts import BatchWriter, write_atomic
from forge_astra.models import Card
from forge_astra.service import Application
from forge_astra.storage import Store
from forge_astra.workflow import Workflow

log = logging.getLogger(__name__)


def cases() -> list[dict]:
    return json.loads(files("forge_astra").joinpath("benchmarks/cards.json").read_text())


def executable(script: str) -> str:
    """Exclude Oracle and descriptions so prose cannot satisfy behavior assertions."""
    lines = []
    for line in script.splitlines():
        if not line.startswith(("A:", "K:", "T:", "R:", "S:", "SVar:")):
            continue
        parts = line.split("|")
        parts = [
            p.strip()
            for p in parts
            if not re.match(
                r"\s*(?:SpellDescription|TriggerDescription|Description|StackDescription)\$", p
            )
        ]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def assess(case: dict, state: dict) -> list[str]:
    expected = case.get("expected_status", "draft")
    failures = []
    if state.get("status") != expected:
        failures.append(f"Expected {expected}, got {state.get('status')}")
    if expected == "blocked":
        if state.get("script"):
            failures.append("Blocked mechanic produced a script")
        return failures
    script = state.get("script", "")
    card = Card.model_validate(case["card"])
    actual_names = re.findall(r"^Name:(.+)$", script, re.M)
    if actual_names != [f.name for f in card.faces]:
        failures.append("Script did not preserve all face identities")
    code = executable(script)
    for check in case["checks"]:
        # Fields on the same ability are unordered in Forge. Check their relationship
        # without requiring a reference script's serialization order.
        fragments = check["pattern"].split(r"[^\n]*")
        count = sum(
            all(re.search(fragment, line) for fragment in fragments) for line in code.splitlines()
        )
        if count < check.get("min", 1) or count > check.get("max", 10000):
            failures.append(check["description"])
    return failures


def evaluate(
    application: Application, *, tier: int | None = None, case_id: str | None = None
) -> dict:
    selected = [
        c
        for c in cases()
        if (tier is None or c["tier"] == tier) and (not case_id or c["id"] == case_id)
    ]
    if not selected:
        raise ValueError("No benchmark cases selected")
    return _evaluate_cases(application, selected)


def evaluate_cards(
    application: Application, cards: list[Card], *, holdout_cards: list[Card] | None = None
) -> dict:
    """Evaluate real cards while withholding all supplied cards' upstream scripts."""
    if not cards:
        raise ValueError("No cards selected")
    if len({card.key for card in cards}) != len(cards):
        raise ValueError("Duplicate card identities in sample; select one printing per card")
    selected = [
        {"id": card.key, "tier": None, "card": card.model_dump(mode="json"), "checks": []}
        for card in cards
    ]
    names = {
        name
        for card in [*cards, *(holdout_cards or [])]
        for name in (card.name, *(f.name for f in card.faces))
    }
    with application.corpus.withhold_cards(names) as withheld:
        log.info("Withholding %d upstream scripts for %d sample cards", len(withheld), len(cards))
        return _evaluate_cases(application, selected, withheld=withheld)


def _evaluate_cases(
    application: Application, selected: list[dict], *, withheld: list[dict] | None = None
) -> dict:
    sample = withheld is not None
    mode = "held_out_cards" if sample else "renamed_benchmark"
    run_id = "eval-" + uuid4().hex[:10]
    day = datetime.now().date().isoformat()
    writer = BatchWriter(application.settings.output_dir / "evaluations", day, run_id)
    # Benchmark history and lessons never contaminate the real spoiler queue/knowledge.
    store = Store(application.settings.data_dir / "evaluations" / (run_id + ".sqlite3"))
    graph = Workflow(
        application.settings,
        store,
        application.corpus,
        application.scryfall,
        application.github,
        application.llm,
    ).build()
    results = []
    try:
        for case in selected:
            application.llm.history.clear()
            card = Card.model_validate(case["card"])
            if application.corpus.named(card.name):
                raise ValueError(
                    "Evaluation target still visible in upstream; cannot fairly evaluate"
                )
            log.info("Evaluating %s: %s", mode, card.name)
            with application.telemetry.span(
                "forge-astra.benchmark",
                as_type="span",
                input={"case": case["id"], "tier": case["tier"], "card": card.name},
                metadata={
                    "run_id": run_id,
                    "model": application.settings.llm_model,
                    "evaluation_mode": mode,
                    "withheld_scripts": withheld or [],
                },
            ) as span:
                try:
                    # Checks, expected results and withheld script bodies never enter graph state.
                    state = graph.invoke(
                        {"card": case["card"]},
                        config={
                            "callbacks": application.telemetry.callbacks(),
                            "metadata": {
                                "langfuse_session_id": run_id,
                                "langfuse_tags": [
                                    "forge-astra",
                                    "benchmark",
                                    mode if sample else f"tier-{case['tier']}",
                                    card.set_code,
                                ],
                            },
                            "recursion_limit": 50,
                        },
                    )
                except Exception as exc:
                    log.error("Benchmark %s failed (%s)", case["id"], type(exc).__name__)
                    state = {
                        "card": case["card"],
                        "status": "error",
                        "issues": [type(exc).__name__],
                    }
                state["model_calls"] = list(application.llm.history)
                failures = assess(case, state)
                entry = writer.add(
                    state,
                    application.corpus.commit,
                    {"reason": mode, "withheld_scripts": withheld or []},
                )
                result = {
                    "case": case["id"],
                    "tier": case["tier"],
                    "passed": not failures,
                    "validation_level": "static_and_model_review",
                    "interpretation": (
                        "Static validation and model review only; no card-specific semantic assertions or gameplay execution."
                        if sample
                        else "Pattern mismatches require review; they do not prove a different implementation is functionally wrong. Forge execution is required for functional verification."
                    ),
                    "failures": failures,
                    "artifact": entry,
                }
                results.append(result)
                if span:
                    span.update(output={"passed": not failures, "failures": failures})
                    span.score(
                        name="script-review" if sample else "script-contract",
                        value=int(not failures),
                        data_type="NUMERIC",
                    )
                log.info(
                    "Benchmark %s: %s %s", case["id"], "PASS" if not failures else "FAIL", failures
                )
                write_atomic(writer.path / "results.json", json.dumps(results, indent=2))
                application.telemetry.flush()
        summary = {
            "run_id": run_id,
            "mode": mode,
            "withheld_scripts": withheld or [],
            "model": application.settings.llm_model,
            "upstream_commit": application.corpus.commit,
            "total": len(results),
            "passed": sum(r["passed"] for r in results),
            "results": results,
            "path": str(writer.path.resolve()),
            "gameplay_tested": False,
        }
        write_atomic(writer.path / "summary.json", json.dumps(summary, indent=2))
        return summary
    finally:
        store.close()
        application.telemetry.flush()
