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


def test_missing_oracle_is_not_a_vanilla_card():
    from forge_astra.scripting import metadata_issues

    raw = {
        "id": "incomplete",
        "name": "Incomplete Card",
        "set": "abc",
        "released_at": "2026-10-01",
        "type_line": "Instant",
    }
    card = Card.from_scryfall(raw)
    assert any("complete Oracle" in issue for issue in metadata_issues(card))
    complete = Card.from_scryfall({**raw, "oracle_text": ""})
    assert complete.oracle_complete
    assert card.fingerprint != complete.fingerprint


def test_reminder_sentences_stay_with_their_ability_without_losing_conditions():
    from forge_astra.models import oracle_sentences

    oracle = (
        "Counter target spell. If its mana value was 2 or less, recruit. "
        "(Draw a card, then discard a card. If you discarded a nonland card, create a token.)"
    )
    parts = oracle_sentences(oracle)
    assert len(parts) == 2
    assert parts[1].startswith("If its mana value")
    assert parts[1].endswith("create a token.)")
    assert " ".join(parts) == oracle
    assert oracle_sentences("Draw a card. Then discard a card.") == [
        "Draw a card.",
        "Then discard a card.",
    ]
    nested = "Recruit. (Draw a card. (Keep its identity.) Then discard a card.)"
    assert oracle_sentences(nested) == [nested]
    assert oracle_sentences("Draw a card. (Reminder is incomplete. Keep all of it.") == [
        "Draw a card. (Reminder is incomplete. Keep all of it."
    ]
