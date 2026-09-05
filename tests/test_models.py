from forge_astra.models import Card


def test_multiface_oracle_is_preserved_and_printings_share_identity():
    data = {
        "id": "printing-a",
        "oracle_id": "oracle-a",
        "name": "Dawn // Dusk",
        "set": "abc",
        "released_at": "2026-10-01",
        "layout": "transform",
        "card_faces": [
            {
                "name": "Dawn",
                "type_line": "Creature — Human",
                "oracle_text": "Flying\nDraw a card. Then discard a card.",
            },
            {"name": "Dusk", "type_line": "Creature — Spirit", "oracle_text": "Vigilance"},
        ],
    }
    a = Card.from_scryfall(data)
    b = Card.from_scryfall({**data, "id": "printing-b", "set": "def"})
    assert a.key == b.key
    assert a.fingerprint == b.fingerprint
    assert [c["text"] for c in a.clauses()] == [
        "Flying",
        "Draw a card.",
        "Then discard a card.",
        "Vigilance",
    ]
    b.faces[1].oracle_text = "Menace"
    assert a.fingerprint != b.fingerprint
