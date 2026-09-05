import json
import logging
from contextlib import contextmanager
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from filelock import FileLock

from forge_astra.artifacts import BatchWriter
from forge_astra.config import Settings
from forge_astra.corpus import Corpus
from forge_astra.llm import ChatClient
from forge_astra.models import Card
from forge_astra.observability import Telemetry
from forge_astra.scryfall import Scryfall
from forge_astra.storage import Store, now_iso
from forge_astra.upstream import GitHub, Snapshot
from forge_astra.workflow import Workflow

log = logging.getLogger(__name__)


class Application:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(settings.db_path)
        self.corpus = Corpus(settings.data_dir / "corpus.sqlite3")
        self.github = GitHub(settings.github_token.get_secret_value())
        self.scryfall = Scryfall()
        self.telemetry = Telemetry(settings)
        self.llm = ChatClient(settings, self.telemetry)
        self.snapshot = Snapshot(settings.data_dir / "upstream", self.github)

    def close(self):
        self.telemetry.flush()
        self.store.close()
        self.corpus.close()
        self.github.http.close()
        self.scryfall.http.close()
        self.llm.http.close()

    @contextmanager
    def lock(self):
        with FileLock(self.settings.data_dir / "run.lock", timeout=0):
            yield

    def today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.timezone)).date()

    def sync(self):
        self.github.cache.clear()
        commit = self.snapshot.sync(self.settings.forge_seed)
        self.corpus.index(self.snapshot.path, commit)
        log.info("Indexed upstream %s", commit[:12])
        return commit

    def discover(self, day: date, backfill: bool = False):
        cards = self.scryfall.discover(
            day, self.settings.release_lookback_days, self.settings.scryfall_query
        )
        result = self.store.observe(cards, day, self.settings.scryfall_query or "default", backfill)
        log.info("Discovery: %s", result)
        return result

    def process(self, day: date) -> dict:
        run_id = datetime.now().strftime("%H%M%S") + "-" + uuid4().hex[:8]
        writer = BatchWriter(self.settings.output_dir, str(day), run_id)
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO runs VALUES (?,?,NULL,'running',NULL)", (run_id, now_iso())
            )
        graph = Workflow(
            self.settings, self.store, self.corpus, self.scryfall, self.github, self.llm
        ).build()
        try:
            for row in self.store.queue(self.settings.max_cards):
                card = Card.model_validate_json(row["payload"])
                with self.telemetry.span(
                    "forge-astra.card",
                    as_type="span",
                    input={"card": card.name, "set": card.set_code},
                    metadata={"run_id": run_id, "upstream_commit": self.corpus.commit},
                ) as span:
                    try:
                        state = graph.invoke(
                            {"card": card.model_dump(mode="json")},
                            config={
                                "callbacks": self.telemetry.callbacks(),
                                "metadata": {
                                    "langfuse_session_id": run_id,
                                    "langfuse_tags": ["forge-astra", card.set_code],
                                },
                                "recursion_limit": 50,
                            },
                        )
                    except Exception as exc:
                        # Preserve retryability and isolate failed cards without leaking provider payloads.
                        log.error("Card %s failed (%s)", card.name, type(exc).__name__)
                        state = {
                            "card": card.model_dump(mode="json"),
                            "status": "error",
                            "issues": [
                                f"{type(exc).__name__}: processing failed; check configured services and traces"
                            ],
                        }
                    entry = writer.add(
                        state,
                        self.corpus.commit,
                        {
                            "first_seen": row["first_seen"],
                            "batch_day": row["batch_day"],
                            "reason": row["discovery_reason"],
                            "previewed_at": str(card.previewed_at) if card.previewed_at else None,
                        },
                    )
                    self.store.finish(card.key, state["status"], entry)
                    if state["status"] == "draft":
                        for lesson in state["draft"]["lessons"]:
                            self.store.lesson(
                                lesson,
                                "unverified",
                                {"report": entry["report"], "commit": self.corpus.commit},
                                card.key,
                            )
                    if span:
                        span.update(output={"status": state["status"], "report": entry["report"]})
                    log.info("%s: %s", card.name, state["status"])
            writer.flush()
            result = {"run_id": run_id, "path": str(writer.path.resolve()), "cards": writer.entries}
            with self.store.db:
                self.store.db.execute(
                    "UPDATE runs SET finished_at=?,status='complete',manifest=? WHERE id=?",
                    (now_iso(), json.dumps(result), run_id),
                )
            return result
        except BaseException:
            with self.store.db:
                self.store.db.execute(
                    "UPDATE runs SET finished_at=?,status='interrupted' WHERE id=?",
                    (now_iso(), run_id),
                )
            raise
        finally:
            self.telemetry.flush()
