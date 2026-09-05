"""Checkpointed, per-set evaluations against a single frozen upstream snapshot."""

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from uuid import uuid4

from forge_astra.artifacts import write_atomic
from forge_astra.evaluation import evaluate_cards
from forge_astra.models import Card
from forge_astra.service import Application


def evaluate_sets(
    application: Application,
    cards: list[Card],
    *,
    workers: int = 1,
    holdout_cards: list[Card] | None = None,
) -> dict:
    """Caller must hold the application lock and prepare its corpus before entry."""
    if not cards or len({c.key for c in cards}) != len(cards):
        raise ValueError("Select nonempty cards with unique identities")
    if not 1 <= workers <= 2:
        raise ValueError("Evaluation workers must be between one and two")
    groups = defaultdict(list)
    holdouts = list({card.key: card for card in [*cards, *(holdout_cards or [])]}.values())
    for card in cards:
        groups[card.set_code].append(card)
    campaign_id = "campaign-" + uuid4().hex[:10]
    path = application.settings.output_dir / "campaigns" / campaign_id
    settings = application.settings.model_copy(update={"output_dir": path})
    root, commit = application.corpus.root, application.corpus.commit
    summary = {
        "campaign_id": campaign_id,
        "started_at": datetime.now(UTC).isoformat(),
        "upstream_commit": commit,
        "model": settings.llm_model,
        "workers": workers,
        "holdout_card_count": len(holdouts),
        "total": len(cards),
        "completed": 0,
        "passed": 0,
        "gameplay_tested": False,
        "sets": {},
        "path": str(path.resolve()),
    }
    write_atomic(
        path / "cards.json", json.dumps([c.model_dump(mode="json") for c in cards], indent=2)
    )
    write_atomic(
        path / "holdout-cards.json",
        json.dumps([c.model_dump(mode="json") for c in holdouts], indent=2),
    )
    write_atomic(path / "summary.json", json.dumps(summary, indent=2))

    def run(selected):
        # Each thread owns its SQLite connections, HTTP clients and model history.
        worker = Application(settings)
        try:
            worker.corpus.index(root, commit)  # Cached, while the caller freezes the snapshot.
            return evaluate_cards(worker, selected, holdout_cards=holdouts)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run, selected): code for code, selected in groups.items()}
        for future in as_completed(futures):
            code = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                # Do not leak HTTP payloads or credentials into public summaries.
                result = {"total": len(groups[code]), "passed": 0, "error": type(exc).__name__}
            summary["sets"][code] = result
            summary["completed"] += result.get("total", 0) if "error" not in result else 0
            summary["passed"] += result["passed"]
            write_atomic(path / "summary.json", json.dumps(summary, indent=2))
    summary["finished_at"] = datetime.now(UTC).isoformat()
    write_atomic(path / "summary.json", json.dumps(summary, indent=2))
    return summary
