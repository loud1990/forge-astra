import json
from datetime import UTC, date, datetime, timedelta
from threading import Event

import pytest
from filelock import FileLock, Timeout
from typer.testing import CliRunner

from forge_astra.cli import app
from forge_astra.config import Settings
from forge_astra.models import Card
from forge_astra.service import Application
from forge_astra.storage import Store, now_iso
from forge_astra.worker import poll_once


@pytest.fixture
def queued_application(tmp_path, monkeypatch):
    application = Application(
        Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "output",
            max_cards=2,
            langfuse_enabled=False,
        )
    )
    calls = []

    class Graph:
        def invoke(self, state, config):
            identifier = state["card"]["id"]
            calls.append(identifier)
            if identifier == "0":
                raise RuntimeError("Provider unavailable")
            return {**state, "status": "blocked" if identifier == "1" else "already_upstream"}

    monkeypatch.setattr("forge_astra.service.Workflow.build", lambda _: Graph())
    for i in range(7):
        card = Card.from_scryfall(
            {
                "id": str(i),
                "name": f"Queue Trial {i}",
                "set": "tst",
                "released_at": "2026-10-01",
                "mana_cost": "{R}",
                "type_line": "Instant",
                "oracle_text": "Deal three damage.",
            }
        )
        application.store.enqueue(card, date(2026, 9, 5))
    try:
        yield application, calls
    finally:
        application.close()


def test_drain_processes_all_batches_without_repeating_failures(queued_application):
    application, calls = queued_application
    batches = list(application.drain(date(2026, 9, 5)))
    assert [len(batch["cards"]) for batch in batches] == [2, 2, 2, 1]
    assert len(calls) == 7 and len(set(calls)) == 7
    assert {row["key"] for row in application.store.queue(20)} == {"0", "1"}
    again = list(application.drain(date(2026, 9, 5)))
    assert len(again) == 1 and set(calls[7:]) == {"0", "1"}


def test_shutdown_preserves_unfinished_cards_for_restart(queued_application):
    application, calls = queued_application
    stopping = Event()
    batches = list(
        application.drain(
            date(2026, 9, 5), should_stop=stopping.is_set, on_card=lambda _: stopping.set()
        )
    )
    assert len(calls) == 1
    assert len(batches) == 1 and batches[0]["interrupted"]
    run = application.store.db.execute("SELECT status,manifest FROM runs").fetchone()
    assert run["status"] == "interrupted" and json.loads(run["manifest"])["interrupted"]
    application.store.close()
    application.store = Store(application.settings.db_path)
    assert sum(row["status"] == "pending" for row in application.store.queue(20)) == 6
    list(application.drain(date(2026, 9, 5)))
    assert set(calls[1:]) == {str(i) for i in range(7)}
    assert not any(row["status"] == "pending" for row in application.store.queue(20))


def test_abandoned_runs_recover_only_after_obtaining_the_worker_lock(queued_application):
    application, _ = queued_application
    with application.store.db:
        application.store.db.execute(
            "INSERT INTO runs VALUES (?,?,NULL,'running',NULL)", ("old", now_iso())
        )
    with FileLock(application.settings.data_dir / "run.lock"):
        with pytest.raises(Timeout), application.lock():
            pytest.fail("The second process must not acquire an active lock")
        assert application.store.db.execute("SELECT status FROM runs").fetchone()[0] == "running"
    with application.lock():
        assert (
            application.store.db.execute("SELECT status FROM runs").fetchone()[0] == "interrupted"
        )
        assert len(application.store.queue(20)) == 7


def test_worker_syncs_once_and_preserves_errors_from_earlier_batches(
    queued_application, monkeypatch
):
    application, calls = queued_application
    phases = []
    monkeypatch.setattr("forge_astra.worker.Application", lambda _: application)
    monkeypatch.setattr(application, "sync", lambda: phases.append("sync"))
    monkeypatch.setattr(application, "discover", lambda _: phases.append("discover"))
    result = poll_once(application.settings, Event())
    assert phases == ["sync", "discover"] and len(calls) == 7
    assert result["status"] == "card_errors" and result["errors"] == 1
    assert result["processed"] == 7 and result["phase"] == "idle"
    assert json.loads((application.settings.data_dir / "health.json").read_text()) == result


def test_worker_initialization_failure_writes_an_unhealthy_record(tmp_path, monkeypatch):
    def fail(_):
        raise RuntimeError("Initialization failed")

    monkeypatch.setattr("forge_astra.worker.Application", fail)
    settings = Settings(_env_file=None, data_dir=tmp_path, langfuse_enabled=False)
    result = poll_once(settings, Event())
    assert result["status"] == "error" and result["processed"] == 0
    assert json.loads((tmp_path / "health.json").read_text())["status"] == "error"


def test_busy_worker_does_not_overwrite_the_active_workers_health(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, langfuse_enabled=False)
    original = '{"status":"running","phase":"generation"}'
    (tmp_path / "health.json").write_text(original)
    with FileLock(tmp_path / "run.lock"):
        assert poll_once(settings, Event())["status"] == "busy"
    assert (tmp_path / "health.json").read_text() == original


@pytest.mark.parametrize(
    "status,phase,stale,exit_code",
    [
        ("running", "generation", False, 0),
        ("running", "generation", True, 1),
        ("card_errors", "idle", False, 1),
        ("ok", "stopped", False, 1),
    ],
)
def test_health_uses_actual_progress_during_long_polls(tmp_path, status, phase, stale, exit_code):
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    (tmp_path / "health.json").write_text(
        json.dumps(
            {
                "last_poll": old,
                "last_activity": old if stale else now_iso(),
                "status": status,
                "phase": phase,
            }
        )
    )
    config = tmp_path / "test.env"
    config.write_text(f"ASTRA_DATA_DIR={tmp_path}\n")
    result = CliRunner().invoke(app, ["--env-file", str(config), "health"])
    assert result.exit_code == exit_code, result.output
