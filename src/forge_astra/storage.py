import json
import sqlite3
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path

from forge_astra.models import Card, digest


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cards (
            key TEXT PRIMARY KEY, name TEXT NOT NULL, fingerprint TEXT NOT NULL,
            payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            batch_day TEXT NOT NULL, discovery_reason TEXT NOT NULL,
            status TEXT NOT NULL, report TEXT, attempts INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS lessons (
            id TEXT PRIMARY KEY, card_key TEXT, content TEXT NOT NULL,
            status TEXT NOT NULL, provenance TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS mechanics (
            name TEXT PRIMARY KEY, pattern TEXT NOT NULL, pr INTEGER,
            reason TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
            status TEXT NOT NULL, manifest TEXT);
        """)

    def close(self):
        self.db.close()

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def observe(self, cards: list[Card], day: date, scope: str, backfill: bool = False) -> dict:
        """Commit a complete, paginated scan and its durable work queue together."""
        baseline = self.get_meta("scan:" + scope) is None
        counts = {"new": 0, "changed": 0, "baseline": 0}
        timestamp = now_iso()
        with self.db:
            for card in cards:
                old = self.db.execute("SELECT * FROM cards WHERE key=?", (card.key,)).fetchone()
                if old:
                    changed = old["fingerprint"] != card.fingerprint
                    self.db.execute(
                        "UPDATE cards SET payload=?,fingerprint=?,last_seen=? WHERE key=?",
                        (card.model_dump_json(), card.fingerprint, timestamp, card.key),
                    )
                    if changed:
                        counts["changed"] += 1
                        self.db.execute(
                            "UPDATE cards SET status='pending',batch_day=?,discovery_reason='oracle_changed',report=NULL WHERE key=?",
                            (str(day), card.key),
                        )
                    continue
                if backfill:
                    reason = "backfill"
                elif card.previewed_at == day:
                    reason = "preview_date"
                elif not baseline:
                    reason = "first_seen" if not card.previewed_at else "late_arrival"
                else:
                    reason = "baseline"
                status = "baseline" if reason == "baseline" else "pending"
                counts["baseline" if status == "baseline" else "new"] += 1
                self.db.execute(
                    "INSERT INTO cards(key,name,fingerprint,payload,first_seen,last_seen,batch_day,discovery_reason,status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        card.key,
                        card.name,
                        card.fingerprint,
                        card.model_dump_json(),
                        timestamp,
                        timestamp,
                        str(day),
                        reason,
                        status,
                    ),
                )
            self.set_meta("scan:" + scope, timestamp)
        return counts

    def enqueue(self, card: Card, day: date, reason: str = "explicit_import"):
        with self.db:
            self.db.execute(
                "INSERT INTO cards(key,name,fingerprint,payload,first_seen,last_seen,batch_day,discovery_reason,status) VALUES (?,?,?,?,?,?,?,?, 'pending') "
                "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,fingerprint=excluded.fingerprint,batch_day=excluded.batch_day,discovery_reason=excluded.discovery_reason,status='pending'",
                (
                    card.key,
                    card.name,
                    card.fingerprint,
                    card.model_dump_json(),
                    now_iso(),
                    now_iso(),
                    str(day),
                    reason,
                ),
            )

    def queue(self, limit: int) -> list[dict]:
        # A killed process leaves no in-progress lease; a later invocation retries the card.
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM cards WHERE status IN ('pending','error','blocked') "
                "ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'error' THEN 1 ELSE 2 END, last_seen,key LIMIT ?",
                (limit,),
            )
        ]

    def finish(self, key: str, status: str, report: dict):
        with self.db:
            self.db.execute(
                "UPDATE cards SET status=?,report=?,attempts=attempts+1 WHERE key=?",
                (status, json.dumps(report), key),
            )

    def retry(self, key: str):
        with self.db:
            result = self.db.execute("UPDATE cards SET status='pending' WHERE key=?", (key,))
            if not result.rowcount:
                raise ValueError(f"Unknown card key: {key}")

    def lesson(self, content: str, status: str, provenance: dict, card_key: str | None = None):
        identifier = digest([content, provenance])[:24]
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO lessons VALUES (?,?,?,?,?,?,?)",
                (identifier, card_key, content, status, json.dumps(provenance), now_iso()),
            )
        return identifier

    def knowledge(self, query: str) -> dict:
        words = set(query.casefold().split())
        rows = [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM lessons WHERE status!='rejected' ORDER BY created_at DESC LIMIT 500"
            )
        ]
        rows.sort(
            key=lambda r: (
                r["status"] == "reviewed",
                len(words & set(r["content"].casefold().split())),
            ),
            reverse=True,
        )
        return {
            "seed": files("forge_astra").joinpath("knowledge/seed.md").read_text(),
            "lessons": rows[:12],
        }

    def track_mechanic(self, name: str, pattern: str, reason: str, pr: int | None = None):
        with self.db:
            self.db.execute(
                "INSERT INTO mechanics VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                "pattern=excluded.pattern,pr=COALESCE(excluded.pr,mechanics.pr),reason=excluded.reason,updated_at=excluded.updated_at",
                (name.casefold(), pattern, pr, reason, now_iso()),
            )

    def mechanics(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM mechanics ORDER BY name")]
