import re
from datetime import date, timedelta
from urllib.parse import urlparse

from forge_astra.http import JsonHTTP, RemoteError
from forge_astra.models import Card, normalize


class Scryfall:
    def __init__(self, http: JsonHTTP | None = None):
        self.http = http or JsonHTTP(
            "https://api.scryfall.com",
            interval=0.12,
            headers={
                "User-Agent": "ForgeAstra/0.1 (MTG card scripting research)",
                "Accept": "application/json",
            },
        )
        self.cache: dict[str, list[dict]] = {}

    def search(self, query: str, *, max_pages: int | None = None) -> list[dict]:
        path = "/cards/search"
        params = {"q": query, "unique": "cards", "order": "name"}
        result = []
        visited = set()
        while True:
            if path in visited:
                raise RemoteError("Scryfall pagination loop")
            visited.add(path)
            page = self.http.request("GET", path, params=params, empty_404=True)
            if page is None:
                if len(visited) > 1:
                    raise RemoteError("Scryfall pagination returned a missing page")
                return result
            result.extend(page["data"])
            if not page.get("has_more") or (max_pages and len(visited) >= max_pages):
                return result
            path = page["next_page"]
            parsed = urlparse(path)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "api.scryfall.com"
                or parsed.path != "/cards/search"
            ):
                raise RemoteError("Unexpected Scryfall pagination URL")
            params = None

    def discover(self, day: date, lookback_days: int, query: str = "") -> list[Card]:
        window = query or f"date>={day - timedelta(days=lookback_days)}"
        raw = self.search(f"game:paper lang:en ({window})")
        cards = {}
        for data in raw:
            if data.get("lang", "en") != "en" or "paper" not in data.get("games", ["paper"]):
                continue
            if data.get("layout") in {"token", "double_faced_token", "art_series", "emblem"}:
                continue
            card = Card.from_scryfall(data)
            # Every printing of the same game object shares a queue key.
            existing = cards.get(card.key)
            if not existing or (card.previewed_at or date.min) > (
                existing.previewed_at or date.min
            ):
                cards[card.key] = card
        return list(cards.values())

    def analogues(self, clause: str, card_name: str) -> tuple[list[dict], list[str]]:
        phrase = clause.replace(card_name, "~")
        phrase = re.sub(r"\([^)]*\)", "", phrase).strip().rstrip(".")
        phrase = phrase.replace('"', "")
        if not phrase:
            return [], []
        queries = [f'game:paper o:"{phrase}"']
        words = [
            w
            for w in normalize(phrase).split()
            if w
            not in {
                "a",
                "an",
                "the",
                "of",
                "to",
                "and",
                "then",
                "you",
                "your",
                "it",
                "this",
                "that",
            }
        ]
        if len(words) > 4:
            queries.append("game:paper " + " ".join(f'o:"{w}"' for w in words[:7]))
        tried = []
        for query in queries:
            tried.append(query)
            if query not in self.cache:
                self.cache[query] = self.search(query, max_pages=1)
            if self.cache[query]:
                return self.cache[query], tried
        return [], tried
