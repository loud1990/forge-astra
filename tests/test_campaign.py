import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_workflow import renamed_bolt

from forge_astra import campaign
from forge_astra.config import Settings
from forge_astra.corpus import Corpus


@pytest.mark.parametrize("expanded", [False, True])
def test_campaign_isolates_workers_checkpoints_sets_and_continues_on_error(
    corpus, tmp_path, monkeypatch, expanded
):
    cards = [renamed_bolt(code) for code in ("abc", "def", "ghi")]
    cards[0].name = cards[0].faces[0].name = "Lightning Bolt"
    cards[1].name = cards[1].faces[0].name = "Bird"
    extra = renamed_bolt("extra")
    extra.name = extra.faces[0].name = "Unsupported"
    all_holdouts = cards + ([extra] if expanded else [])
    settings = Settings(_env_file=None, output_dir=tmp_path / "out", langfuse_enabled=False)
    parent = SimpleNamespace(settings=settings, corpus=corpus)
    barrier = threading.Barrier(2)
    closed = []
    threads = set()

    class Worker:
        def __init__(self, settings):
            self.settings = settings
            self.corpus = Corpus(tmp_path / "corpus.db")
            threads.add(threading.get_ident())

        def close(self):
            self.corpus.close()
            closed.append(self)

    def evaluate(worker, selected, *, holdout_cards):
        assert len(selected) == 1
        assert holdout_cards == all_holdouts
        with worker.corpus.withhold_cards(c.name for c in holdout_cards):
            assert worker.corpus.named("Lightning Bolt") == []
            assert worker.corpus.named("Bird") == []
            assert bool(worker.corpus.named("Unsupported")) is not expanded
            if selected[0].set_code in {"abc", "def"}:
                barrier.wait(timeout=10)
            if selected[0].set_code == "def":
                raise RuntimeError("private response must not leak")
            return {"total": 1, "passed": 1, "results": [selected[0].set_code]}

    monkeypatch.setattr(campaign, "Application", Worker)
    monkeypatch.setattr(campaign, "evaluate_cards", evaluate)
    result = campaign.evaluate_sets(parent, cards, workers=2, holdout_cards=all_holdouts)
    assert result["total"] == 3 and result["completed"] == result["passed"] == 2
    assert len(threads) == 2 and len(closed) == 3
    assert result["holdout_card_count"] == len(all_holdouts)
    assert len(json.loads((Path(result["path"]) / "holdout-cards.json").read_text())) == len(
        all_holdouts
    )
    assert result["sets"]["def"]["error"] == "RuntimeError"
    assert result["sets"]["abc"]["results"] == ["abc"]
    assert result["sets"]["ghi"]["results"] == ["ghi"]
    saved = (Path(result["path"]) / "summary.json").read_text()
    assert json.loads(saved) == result
    assert "private response" not in saved
    assert corpus.named("Lightning Bolt") and corpus.named("Bird")


def test_campaign_rejects_invalid_inputs():
    card = renamed_bolt()
    for cards, workers in (([], 1), ([card, card], 1), ([card], 0), ([card], 3)):
        with pytest.raises(ValueError):
            campaign.evaluate_sets(None, cards, workers=workers)
