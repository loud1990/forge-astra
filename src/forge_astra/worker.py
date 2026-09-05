import json
import logging
from contextlib import ExitStack
from threading import Event

from filelock import Timeout

from forge_astra.artifacts import write_atomic
from forge_astra.config import Settings
from forge_astra.service import Application
from forge_astra.storage import now_iso

log = logging.getLogger(__name__)


def poll_once(settings: Settings, stopping: Event) -> dict:
    """Refresh sources once, drain the queue, and publish actual worker activity."""
    application = None
    publish = True
    status = "ok"
    record = {"last_poll": now_iso(), "processed": 0, "errors": 0}

    def activity(phase: str, status: str = "running"):
        record.update(last_activity=now_iso(), phase=phase, status=status)
        write_atomic(settings.data_dir / "health.json", json.dumps(record))

    def card_finished(entry: dict):
        record["processed"] += 1
        record["errors"] += int(entry["status"] == "error")
        activity("generation")

    with ExitStack() as lifetime:
        try:
            application = Application(settings)
            lifetime.enter_context(application.lock())
            activity("upstream")
            application.sync()
            if not stopping.is_set():
                day = application.today()
                activity("discovery")
                application.discover(day)
                activity("generation")
                for _ in application.drain(day, should_stop=stopping.is_set, on_card=card_finished):
                    pass
            if record["errors"]:
                status = "card_errors"
        except Timeout:
            # Another process owns this data directory and its health record.
            publish = False
            status = "busy"
            log.info("Worker lock is busy; will retry next interval")
        except Exception as exc:
            status = "error"
            log.error("Poll failed (%s); will retry next interval", type(exc).__name__)
        finally:
            if application:
                try:
                    application.close()
                except Exception as exc:
                    status = "error"
                    log.error("Worker cleanup failed (%s)", type(exc).__name__)
            if publish:
                record["last_poll"] = now_iso()
                activity("stopped" if stopping.is_set() else "idle", status)
    return {**record, "status": status}
