from datetime import date

import httpx
import pytest

from forge_astra.http import JsonHTTP, RemoteError
from forge_astra.models import Card
from forge_astra.scryfall import Scryfall
from forge_astra.storage import Store


def card(identifier="a", preview=None, text="Flying"):
    return Card.from_scryfall(
        {
            "id": identifier,
            "oracle_id": identifier,
            "name": "Test " + identifier,
            "set": "abc",
            "released_at": "2026-10-01",
            "type_line": "Creature — Bird",
            "oracle_text": text,
            "preview": {"previewed_at": preview},
        }
    )


def test_baseline_today_dedup_corrections_and_durable_retry(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    day = date(2026, 9, 5)
    old, today = card(), card("b", str(day))
    assert store.observe([old, today], day, "default") == {"new": 1, "changed": 0, "baseline": 1}
    assert [r["key"] for r in store.queue(20)] == ["b"]
    store.finish("b", "draft", {})
    store.close()
    store = Store(path)
    assert store.observe([old, today, card("c")], day, "default")["new"] == 1
    assert [r["key"] for r in store.queue(20)] == ["c"]
    store.finish("c", "error", {})
    store.observe([card("b", str(day), "Vigilance")], day, "default")
    assert {r["key"] for r in store.queue(20)} == {"b", "c"}
    assert (
        store.db.execute("SELECT discovery_reason FROM cards WHERE key='b'").fetchone()[0]
        == "oracle_changed"
    )
    store.close()


def test_discovery_reads_all_pages_and_rejects_foreign_next_page():
    def handler(request):
        if "page=2" in str(request.url):
            return httpx.Response(200, json={"data": [{"name": "Second"}], "has_more": False})
        return httpx.Response(
            200,
            json={
                "data": [{"name": "First"}],
                "has_more": True,
                "next_page": "https://api.scryfall.com/cards/search?page=2",
            },
        )

    client = JsonHTTP("https://api.scryfall.com", transport=httpx.MockTransport(handler))
    assert [c["name"] for c in Scryfall(client).search("test")] == ["First", "Second"]
    client.close()
    bad = JsonHTTP(
        "https://api.scryfall.com",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"data": [], "has_more": True, "next_page": "https://evil.example/"}
            )
        ),
    )
    with pytest.raises(RemoteError, match="pagination URL"):
        Scryfall(bad).search("test")
    bad.close()


def test_missing_later_page_is_not_a_successful_partial_scan():
    def handler(request):
        if "page=2" in str(request.url):
            return httpx.Response(404, json={"object": "error"})
        return httpx.Response(
            200,
            json={
                "data": [{"name": "First"}],
                "has_more": True,
                "next_page": "https://api.scryfall.com/cards/search?page=2",
            },
        )

    http = JsonHTTP("https://api.scryfall.com", transport=httpx.MockTransport(handler))
    with pytest.raises(RemoteError, match="missing page"):
        Scryfall(http).search("test")
    http.close()


def test_late_preview_date_can_promote_a_baselined_card(tmp_path):
    store = Store(tmp_path / "state.db")
    day = date(2026, 9, 5)
    store.observe([card()], day, "default")
    assert store.queue(10) == []
    assert store.observe([card(preview=str(day))], day, "default")["new"] == 1
    assert store.queue(10)[0]["discovery_reason"] == "preview_date"
    store.close()
