import json
import re
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

from forge_astra.models import normalize
from forge_astra.upstream import CARDS, DOCS, GAME, TOKENS


def active_lines(script: str) -> list[str]:
    return [
        line
        for line in script.splitlines()
        if line.startswith(("A:", "K:", "T:", "S:", "R:", "SVar:"))
    ]


def enum_names(text: str) -> set[str]:
    return set(re.findall(r"^\s+(\w+)\s*\([^;\n]*\.class", text, re.M))


class Corpus:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,kind TEXT,name TEXT,
                oracle TEXT,body TEXT,path TEXT,commit_sha TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED,name,oracle);
        """)
        # Connection-local exclusions never change the persistent index or checkout.
        self.db.executescript("""
            CREATE TEMP TABLE withheld_scripts(id TEXT PRIMARY KEY);
            CREATE TEMP VIEW visible_evidence AS
                SELECT * FROM main.evidence
                WHERE id NOT IN (SELECT id FROM withheld_scripts);
        """)
        self.root = Path()
        self.commit = ""
        self.capabilities: dict[str, set[str]] = {}

    def close(self):
        self.db.close()

    @contextmanager
    def withhold_cards(self, names: Iterable[str]):
        """Hide entire card scripts, including all faces, from every retrieval path."""
        requested = {name.strip().casefold() for name in names}
        entries = [
            dict(row)
            for row in self.db.execute("SELECT id,name,path FROM evidence WHERE kind='script'")
            if requested.intersection(
                {row["name"].casefold(), *(n.strip().casefold() for n in row["name"].split(" // "))}
            )
        ]
        previous = list(self.db.execute("SELECT id FROM withheld_scripts"))
        try:
            with self.db:
                self.db.executemany(
                    "INSERT OR IGNORE INTO withheld_scripts VALUES (?)",
                    [(entry["id"],) for entry in entries],
                )
            yield entries
        finally:
            with self.db:
                self.db.execute("DELETE FROM withheld_scripts")
                self.db.executemany("INSERT INTO withheld_scripts VALUES (?)", previous)

    def index(self, root: Path, commit: str):
        self.root, self.commit = root, commit
        row = self.db.execute("SELECT value FROM metadata WHERE key='commit'").fetchone()
        if row and row[0] == commit:
            self.capabilities = {
                k: set(v)
                for k, v in json.loads(
                    self.db.execute(
                        "SELECT value FROM metadata WHERE key='capabilities'"
                    ).fetchone()[0]
                ).items()
            }
            return
        capabilities = {
            k: set() for k in ("api", "trigger", "replacement", "keyword", "param", "static")
        }
        for key, relative in [
            ("api", f"{GAME}/ability/ApiType.java"),
            ("trigger", f"{GAME}/trigger/TriggerType.java"),
            ("replacement", f"{GAME}/replacement/ReplacementType.java"),
        ]:
            capabilities[key] = enum_names((root / relative).read_text())
        keyword_source = (root / GAME / "keyword/Keyword.java").read_text()
        capabilities["keyword"] = set(re.findall(r'^\s+\w+\("([^"]+)"', keyword_source, re.M)) - {
            ""
        }
        with self.db:
            self.db.execute("DELETE FROM evidence")
            self.db.execute("DELETE FROM search")
            for folder, kind in [(CARDS, "script"), (TOKENS, "token")]:
                for path in sorted((root / folder).rglob("*.txt")):
                    body = path.read_text(encoding="utf-8")
                    names = re.findall(r"^Name:(.+)$", body, re.M)
                    name = " // ".join(names)
                    oracle = "\n".join(re.findall(r"^Oracle:(.*)$", body, re.M)).replace(
                        "\\n", "\n"
                    )
                    for face_name in sorted(names, key=len, reverse=True):
                        oracle = oracle.replace(face_name, "CARDNAME")
                    relative = path.relative_to(root).as_posix()
                    self.add(relative, kind, name, oracle, body, relative)
                    active = "\n".join(active_lines(body))
                    capabilities["param"].update(re.findall(r"(?:^|[:|])\s*(\w+)\$", active, re.M))
                    capabilities["static"].update(re.findall(r"^S:Mode\$\s*(\w+)", active, re.M))
                    capabilities["static"].update(
                        re.findall(r"^SVar:[^:]+:Mode\$\s*(\w+)", active, re.M)
                    )
            for path in sorted((root / DOCS).glob("*.md")):
                body = path.read_text()
                # Chunk on headings to retain relevant sections within model context budgets.
                for i, chunk in enumerate(re.split(r"(?m)(?=^#{1,4} )", body)):
                    for j, offset in enumerate(range(0, len(chunk), 5000)):
                        part = chunk[offset : offset + 5000]
                        relative = path.relative_to(root).as_posix()
                        self.add(f"{relative}#{i}-{j}", "doc", path.stem, part, part, relative)
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('commit',?)", (commit,))
            self.db.execute(
                "INSERT OR REPLACE INTO metadata VALUES ('capabilities',?)",
                (json.dumps({k: sorted(v) for k, v in capabilities.items()}),),
            )
        self.capabilities = capabilities

    def add(self, identifier: str, kind: str, name: str, oracle: str, body: str, path: str):
        self.db.execute(
            "INSERT INTO evidence VALUES (?,?,?,?,?,?,?)",
            (identifier, kind, name, oracle, body, path, self.commit),
        )
        self.db.execute("INSERT INTO search VALUES (?,?,?)", (identifier, name, normalize(oracle)))

    def get(self, identifier: str) -> dict | None:
        row = self.db.execute("SELECT * FROM visible_evidence WHERE id=?", (identifier,)).fetchone()
        return dict(row) if row else None

    def named(self, name: str) -> list[dict]:
        # Face names are resolved from indexed metadata, not guessed filenames.
        rows = self.db.execute(
            "SELECT * FROM visible_evidence WHERE kind='script' AND (name=? COLLATE NOCASE OR name LIKE ? OR name LIKE ?)",
            (name, name + " // %", "% // " + name),
        ).fetchall()
        return [dict(r) for r in rows]

    def search(self, text: str, limit: int = 6, kind: str = "script") -> list[dict]:
        words = list(dict.fromkeys(normalize(text).split()))
        words = [
            w
            for w in words
            if w not in {"a", "the", "and", "of", "to", "cardname", "this", "that", "you", "your"}
        ]
        if not words:
            return []
        match = " OR ".join('"' + w + '"' for w in words[:40])
        rows = self.db.execute(
            "SELECT e.* FROM search JOIN visible_evidence e ON e.id=search.id "
            "WHERE search MATCH ? AND e.kind=? ORDER BY bm25(search,0,2,1),e.id LIMIT ?",
            (match, kind, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mechanic_examples(self, name: str, limit: int = 4) -> list[dict]:
        # Require the named mechanic in executable syntax, not only prose or an enum.
        needle = normalize(name).replace(" ", "")
        if not needle:
            return []
        rows = self.db.execute(
            "SELECT * FROM visible_evidence WHERE kind='script' AND (body LIKE ? OR oracle LIKE ?) LIMIT 300",
            ("%" + name + "%", "%" + name + "%"),
        )
        matches = []
        for row in rows:
            for line in active_lines(row["body"]):
                tokens = []
                if line.startswith("K:"):
                    tokens.append(line[2:].split(":")[0])
                tokens.extend(re.findall(r"(?:AB|SP|DB|Mode|Event)\$\s*(\w+)", line))
                if any(normalize(t).replace(" ", "") == needle for t in tokens):
                    matches.append(dict(row))
                    break
            if len(matches) >= limit:
                break
        return matches

    def has_keyword_line(self, line: str) -> bool:
        candidates = self.db.execute(
            "SELECT body FROM visible_evidence WHERE kind='script' AND body LIKE ? LIMIT 100",
            ("%" + line + "%",),
        )
        return any(line in active_lines(row[0]) for row in candidates)

    def ability_word_examples(self, name: str, limit: int = 4) -> list[dict]:
        """Find executable implementations whose Oracle ability bears this label."""
        label = re.compile(r"^\s*" + re.escape(name) + r"\s+—", re.I | re.M)
        matches = []
        for row in self.db.execute(
            "SELECT * FROM visible_evidence WHERE kind='script' AND oracle LIKE ? "
            "ORDER BY length(body),id",
            ("%" + name + "%",),
        ):
            if label.search(row["oracle"]) and active_lines(row["body"]):
                matches.append(dict(row))
                if len(matches) >= limit:
                    break
        return matches
