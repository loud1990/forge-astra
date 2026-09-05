import pytest

from forge_astra.artifacts import BatchWriter
from forge_astra.config import Settings
from forge_astra.models import Card, Draft, Plan, Review
from forge_astra.scripting import assemble, deck_text, plan_issues, validate_draft
from forge_astra.storage import Store
from forge_astra.workflow import Workflow


def renamed_bolt(set_code="abc"):
    return Card.from_scryfall(
        {
            "id": "new-" + set_code,
            "name": "Ember Test",
            "set": set_code,
            "mana_cost": "{R}",
            "released_at": "2026-10-01",
            "type_line": "Instant",
            "oracle_text": "Ember Test deals 3 damage to any target.",
            "color_identity": ["R"],
        }
    )


def draft(damage=3):
    return Draft.model_validate(
        {
            "faces": [
                {
                    "lines": [
                        f"A:SP$ DealDamage | ValidTgts$ Any | NumDmg$ {damage} | SpellDescription$ CARDNAME deals {damage} damage to any target."
                    ]
                }
            ],
            "support_cards": [
                {"name": f"Support {i}", "count": 4, "purpose": "damage support"} for i in range(7)
            ],
            "test_plan": ["Damage a player and a creature; confirm exactly 3 damage."],
            "lessons": ["Use the upstream damage primitive."],
        }
    )


def pool():
    return [{"name": f"Support {i}"} for i in range(7)]


class FakeScryfall:
    def analogues(self, text, name):
        return [{"name": "Lightning Bolt"}], [f'o:"{text}"']


class FakeGitHub:
    def implementation_prs(self, name):
        return [{"number": 1, "state": "open"}]

    def merged_in_snapshot(self, number, commit):
        return False, "PR #1 is not merged"


class FakeLLM:
    def __init__(self, block=False, revise=False):
        self.calls = []
        self.block, self.revise = block, revise

    def ask(self, task, context, schema, review=False):
        self.calls.append(schema.__name__)
        if schema is Plan:
            evidence = next(e for e in context["evidence"] if e["name"] == "Lightning Bolt")
            return Plan.model_validate(
                {
                    "clauses": [
                        {
                            "clause_id": c["id"],
                            "explanation": "Reuse damage",
                            "citations": [
                                {"evidence_id": evidence["id"], "quote": "SP$ DealDamage"}
                            ],
                            "needs_engine": self.block,
                            "blocker": "New engine rule" if self.block else "",
                        }
                        for c in context["clauses"]
                    ],
                    "mechanics": [],
                }
            )
        if schema is Draft:
            return draft(2 if self.revise and self.calls.count("Draft") == 1 else 3)
        if schema is Review:
            revise = self.revise and self.calls.count("Review") == 1
            return Review.model_validate(
                {
                    "verdict": "revise" if revise else "pass",
                    "clauses": [
                        {
                            "clause_id": c["id"],
                            "implemented": not revise,
                            "explanation": "Damage must be 3" if revise else "Matches Oracle",
                        }
                        for c in context["clauses"]
                    ],
                    "issues": [],
                    "new_mechanics": [],
                }
            )
        raise AssertionError(schema)


def test_langgraph_revises_and_exports_separate_sets(corpus, tmp_path):
    store = Store(tmp_path / "state.db")
    llm = FakeLLM(revise=True)
    workflow = Workflow(Settings(_env_file=None), store, corpus, FakeScryfall(), FakeGitHub(), llm)
    workflow.support_pool = lambda card: pool()
    result = workflow.build().invoke({"card": renamed_bolt().model_dump(mode="json")})
    assert result["status"] == "draft"
    assert llm.calls == ["Plan", "Draft", "Review", "Draft", "Review"]
    assert "NumDmg$ 3" in result["script"]
    assert "Name:Ember Test" in result["script"]
    assert "Name:Lightning Bolt" not in result["script"]
    writer = BatchWriter(tmp_path / "out", "2026-09-05", "run")
    writer.add(result, corpus.commit, {})
    writer.add({**result, "card": renamed_bolt("def").model_dump(mode="json")}, corpus.commit, {})
    for code in ("abc", "def"):
        assert (writer.path / code / "PR_DRAFT.md").exists()
        assert (writer.path / code / "cardsfolder/e/ember_test.txt").exists()
    deck = deck_text(renamed_bolt(), draft())
    assert "8 Ember Test" in deck
    assert sum(int(line.split()[0]) for line in deck.splitlines() if line[:1].isdigit()) == 60
    store.close()


def test_blocked_plan_never_calls_writer_or_exports_script(corpus, tmp_path):
    store = Store(tmp_path / "state.db")
    llm = FakeLLM(block=True)
    workflow = Workflow(Settings(_env_file=None), store, corpus, FakeScryfall(), FakeGitHub(), llm)
    workflow.support_pool = lambda card: pool()
    result = workflow.build().invoke({"card": renamed_bolt().model_dump(mode="json")})
    assert result["status"] == "blocked"
    assert llm.calls == ["Plan"]
    writer = BatchWriter(tmp_path / "out", "2026-09-05", "run")
    writer.add(result, corpus.commit, {})
    assert not list(writer.path.rglob("*.txt"))
    assert not list(writer.path.rglob("*.dck"))
    store.close()


@pytest.mark.parametrize(
    "line,expected",
    [
        ("A:SP$ Invented | NumDmg$ 3", "Unknown upstream ability"),
        ("A:SP$ DealDamage | Hallucinated$ True", "Unknown upstream parameter"),
        ("T:Mode$ FakeTrigger | Execute$ Missing", "Unknown upstream trigger"),
        ("K:Novelty", "Unproven keyword"),
        ("Name:Wrong Name", "Invalid script line type"),
    ],
)
def test_invalid_dsl_is_rejected(corpus, line, expected):
    value = draft()
    value.faces[0].lines = [line]
    assert any(expected in issue for issue in validate_draft(renamed_bolt(), value, corpus, pool()))


def test_citations_require_executable_evidence(corpus):
    evidence = corpus.named("Lightning Bolt")
    plan = Plan.model_validate(
        {
            "clauses": [
                {
                    "clause_id": "f0c0",
                    "explanation": "Test",
                    "citations": [
                        {
                            "evidence_id": evidence[0]["id"],
                            "quote": "Oracle:Lightning Bolt deals 3 damage to any target.",
                        }
                    ],
                    "needs_engine": False,
                }
            ],
            "mechanics": [],
        }
    )
    assert any("no executable" in issue for issue in plan_issues(renamed_bolt(), plan, evidence))


def test_multiface_metadata_and_hybrid_cost(corpus):
    card = Card.from_scryfall(
        {
            "id": "dfc",
            "name": "Day // Night",
            "set": "abc",
            "layout": "modal_dfc",
            "released_at": "2026-10-01",
            "card_faces": [
                {
                    "name": "Day",
                    "type_line": "Creature — Bird",
                    "power": "1",
                    "toughness": "2",
                    "mana_cost": "{2}{W/U}",
                    "oracle_text": "Flying",
                },
                {"name": "Night", "type_line": "Land", "oracle_text": "{T}: Add {U}."},
            ],
        }
    )
    value = draft()
    value.faces = [
        type(value.faces[0])(lines=["K:Flying"]),
        type(value.faces[0])(lines=["A:AB$ Mana | Cost$ T | Produced$ U"]),
    ]
    script = assemble(card, value)
    assert "ManaCost:2 W/U" in script
    assert "AlternateMode:Modal" in script
    assert script.count("ALTERNATE") == 1
    assert "Name:Night\nManaCost:no cost\nTypes:Land" in script


def test_existing_oracle_does_not_hide_changed_cost(corpus, tmp_path):
    from forge_astra.scripting import metadata_matches

    card = renamed_bolt()
    card.name = card.faces[0].name = "Lightning Bolt"
    card.faces[0].oracle_text = "Lightning Bolt deals 3 damage to any target."
    existing = corpus.named("Lightning Bolt")[0]["body"]
    assert metadata_matches(card, existing)
    card.faces[0].mana_cost = "{1}{R}"
    assert not metadata_matches(card, existing)


def test_generic_implementation_label_does_not_create_false_mechanic_blocker(corpus, tmp_path):
    store = Store(tmp_path / "state.db")
    llm = FakeLLM()
    workflow = Workflow(Settings(_env_file=None), store, corpus, FakeScryfall(), FakeGitHub(), llm)
    state = {
        "card": renamed_bolt().model_dump(mode="json"),
        "evidence": corpus.named("Lightning Bolt"),
    }
    plan = llm.ask("plan", {**state, "clauses": renamed_bolt().clauses()}, Plan)
    state["plan"] = plan.model_dump()
    state["plan"]["mechanics"] = [
        {"name": "Damage Spell", "needs_engine": False, "explanation": "Existing spell ability"}
    ]
    assert workflow.gate(state)["status"] == ""
    store.close()


def test_bad_citation_is_replanned_before_scripting(corpus, tmp_path):
    class RepairLLM(FakeLLM):
        def ask(self, task, context, schema, review=False):
            result = super().ask(task, context, schema, review)
            if schema is Plan and self.calls.count("Plan") == 1:
                result.clauses[0].citations[0].quote = "A fabricated quote"
            return result

    store = Store(tmp_path / "state.db")
    llm = RepairLLM()
    workflow = Workflow(Settings(_env_file=None), store, corpus, FakeScryfall(), FakeGitHub(), llm)
    workflow.support_pool = lambda card: pool()
    result = workflow.build().invoke({"card": renamed_bolt().model_dump(mode="json")})
    assert result["status"] == "draft"
    assert llm.calls == ["Plan", "Plan", "Draft", "Review"]
    assert result["planning_revisions"] == 1
    store.close()


def test_deck_hints_are_not_ability_parameters(corpus):
    value = draft()
    value.faces[0].lines.append("DeckHas:Ability$Damage")
    assert validate_draft(renamed_bolt(), value, corpus, pool()) == []


def test_deck_arithmetic_is_balanced_without_rewriting_the_script():
    from forge_astra.scripting import balance_support

    value = draft()
    value.support_cards = value.support_cards[:5]
    balanced = balance_support(value, pool())
    assert sum(c.count for c in balanced.support_cards) == 28
    assert max(c.count for c in balanced.support_cards) <= 4
    assert balanced.faces == value.faces
    assert all(c.name in {p["name"] for p in pool()} for c in balanced.support_cards)
