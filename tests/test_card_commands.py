import json
from datetime import date

from typer.testing import CliRunner

from forge_astra.cli import app
from forge_astra.models import Card
from forge_astra.storage import Store


def test_card_filters_details_and_pagination_preserve_queue(tmp_path):
    store = Store(tmp_path / "astra.sqlite3")
    day = date(2026, 9, 5)
    for identifier, name, set_code in (
        ("a", "Trial Flame", "tst"),
        ("b", "Trial Tide", "sea"),
        ("c", "Trial Growth", "tst"),
    ):
        card = Card.from_scryfall(
            {
                "id": identifier,
                "name": name,
                "set": set_code,
                "released_at": "2026-10-01",
                "type_line": "Instant",
                "oracle_text": "Draw a card.",
            }
        )
        store.enqueue(card, day)
    store.finish(
        "a",
        "blocked",
        {"blockers": ["Implementation PR is not merged"], "report": "/output/report.json"},
    )
    config = tmp_path / "test.env"
    config.write_text(f"ASTRA_DATA_DIR={tmp_path}\n")
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(app, ["--env-file", str(config), *args])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    before = [(row["key"], row["status"], row["attempts"]) for row in store.queue(20)]
    filtered = invoke("cards", "--status", "blocked", "--set", "TST", "--name", "flame")
    assert [row["card_key"] for row in filtered] == ["a"]
    assert filtered[0]["latest_result"]["blockers"] == ["Implementation PR is not merged"]
    all_cards = invoke("cards")
    assert len(all_cards) == 3
    assert invoke("cards", "--limit", "1", "--offset", "1") == all_cards[1:2]
    # Name filters are literal and bound values cannot alter the SQL query.
    assert invoke("cards", "--name", "' OR 1=1 --") == []
    detail = invoke("show", "a")
    assert detail["card"]["faces"][0]["oracle_text"] == "Draw a card."
    assert detail["latest_result"]["report"] == "/output/report.json"
    assert detail["attempts"] == 1 and detail["discovery_reason"] == "explicit_import"
    assert [(row["key"], row["status"], row["attempts"]) for row in store.queue(20)] == before
    for args in (("show", "unknown"), ("cards", "--status", "bogus"), ("cards", "--limit", "0")):
        assert runner.invoke(app, ["--env-file", str(config), *args]).exit_code != 0
    store.close()
