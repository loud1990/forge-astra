"""Refresh frozen Scryfall inputs. Run with `uv run python scripts/refresh_benchmarks.py`.

Golden checks are diagnostics of executable behavior, not exact-script comparisons.
The generator never sends original names or expectations to the inference endpoint.
"""

import json
import uuid
from pathlib import Path

from forge_astra.models import Card
from forge_astra.scryfall import Scryfall


def check(pattern, description, minimum=1, maximum=10000):
    return {"pattern": pattern, "description": description, "min": minimum, "max": maximum}


SPECS = [
    (
        1,
        "llanowar_elves",
        "Llanowar Elves",
        "Astra Grove Tender",
        [
            check(
                r"^A:AB\$ Mana\b[^\n]*Cost\$ T(?:\s*\||$)[^\n]*Produced\$ G\b",
                "Needs a tap ability producing one green mana",
            ),
            check(r"^A:", "Needs exactly one activated ability", 1, 1),
        ],
    ),
    (
        1,
        "lightning_bolt",
        "Lightning Bolt",
        "Astra Ember Lance",
        [
            check(
                r"^A:SP\$ DealDamage\b[^\n]*ValidTgts\$ Any\b[^\n]*NumDmg\$ 3\b",
                "Needs a spell dealing three damage to any target",
            ),
            check(r"^A:", "Needs exactly one spell ability", 1, 1),
        ],
    ),
    (
        1,
        "murder",
        "Murder",
        "Astra Final Verdict",
        [
            check(
                r"^A:SP\$ Destroy\b[^\n]*ValidTgts\$ Creature(?:\s*\||$)",
                "Needs unconditional destruction of target creature",
            ),
            check(r"Condition\w*\$", "Unconditional destroy must not gain a condition", 0, 0),
        ],
    ),
    (
        1,
        "divination",
        "Divination",
        "Astra Clear Insight",
        [check(r"^A:SP\$ Draw\b[^\n]*NumCards\$ 2\b", "Needs a spell drawing two cards")],
    ),
    (
        1,
        "giant_growth",
        "Giant Growth",
        "Astra Sudden Stature",
        [
            check(r"\bPump\b[^\n]*ValidTgts\$ Creature\b", "Needs to pump a target creature"),
            check(r"NumAtt\$ \+?3\b", "Needs +3 power"),
            check(r"NumDef\$ \+?3\b", "Needs +3 toughness"),
            check(r"Permanent\$ True", "Pump must expire at end of turn", 0, 0),
        ],
    ),
    (
        2,
        "fatal_push",
        "Fatal Push",
        "Astra Quiet Removal",
        [
            check(r"SP\$ Destroy\b", "Needs a destroy spell"),
            check(
                r"ValidTgts\$ Creature(?:\s*\||$)",
                "Mana value belongs to the resolution condition, not targeting restriction",
            ),
            check(
                r"ConditionDefined\$ Targeted", "Needs to test the targeted creature at resolution"
            ),
            check(
                r"ConditionPresent\$ Creature\.cmcLE\w+", "Needs the mana-value resolution check"
            ),
            check(r"Count\$\s*Revolt\.4\.2", "Needs revolt's four/two thresholds"),
        ],
    ),
    (
        2,
        "tragic_slip",
        "Tragic Slip",
        "Astra Grave Diminution",
        [
            check(r"SP\$ Pump\b[^\n]*ValidTgts\$ Creature\b", "Needs to weaken target creature"),
            check(r"NumAtt\$ -X\b", "Power reduction must use the conditional amount"),
            check(r"NumDef\$ -X\b", "Toughness reduction must use the conditional amount"),
            check(r"Count\$\s*Morbid\.13\.1", "Needs morbid's thirteen/one amounts"),
        ],
    ),
    (
        2,
        "wild_slash",
        "Wild Slash",
        "Astra Fierce Spark",
        [
            check(
                r"ConditionPresent\$ Creature\.YouCtrl\+powerGE4",
                "Prevention suppression needs ferocious",
            ),
            check(r"Mode\$ CantPreventDamage", "Needs a damage-prevention suppression effect"),
            check(
                r"DB\$ DealDamage[^\n]*ValidTgts\$ Any[^\n]*NumDmg\$ 2\b",
                "Needs the separate two-damage ability regardless of ferocious",
            ),
        ],
    ),
    (
        3,
        "jace_beleren",
        "Jace Beleren",
        "Astra Memory Keeper",
        [
            check(r"^A:AB\$", "Needs three separate loyalty abilities", 3, 3),
            check(
                r"Cost\$ AddCounter<2/LOYALTY>[^\n]*Defined\$ Player",
                "+2 must make all players draw",
            ),
            check(
                r"Cost\$ SubCounter<1/LOYALTY>[^\n]*ValidTgts\$ Player",
                "-1 must make a target player draw",
            ),
            check(
                r"AB\$ Mill[^\n]*SubCounter<10/LOYALTY>[^\n]*NumCards\$ 20", "-10 must mill twenty"
            ),
            check(r"Planeswalker\$ True", "All three abilities need loyalty timing", 3, 3),
        ],
    ),
    (
        3,
        "liliana_of_the_veil",
        "Liliana of the Veil",
        "Astra Veil Arbiter",
        [
            check(r"^A:AB\$", "Needs three separate loyalty abilities", 3, 3),
            check(
                r"AB\$ Discard[^\n]*AddCounter<1/LOYALTY>[^\n]*Defined\$ Player",
                "+1 must make each player discard",
            ),
            check(
                r"AB\$ Sacrifice[^\n]*SubCounter<2/LOYALTY>[^\n]*SacValid\$ Creature",
                "-2 must make target player sacrifice a creature",
            ),
            check(
                r"AB\$ TwoPiles[^\n]*SubCounter<6/LOYALTY>",
                "-6 must partition permanents into piles",
            ),
            check(
                r"DB\$ SacrificeAll[^\n]*Permanent\.IsRemembered", "Chosen pile must be sacrificed"
            ),
        ],
    ),
    (
        4,
        "bonecrusher_giant",
        "Bonecrusher Giant",
        "Astra Stone Sentinel",
        [
            check(
                r"^T:Mode\$ BecomesTarget[^\n]*ValidTarget\$ Card\.Self[^\n]*ValidSource\$ Spell",
                "Front must trigger when targeted by a spell",
            ),
            check(
                r"Defined\$ TriggeredSourceController[^\n]*NumDmg\$ 2",
                "Front must damage the targeting spell's controller",
            ),
            check(r"Mode\$ CantPreventDamage", "Adventure must suppress damage prevention"),
            check(
                r"DB\$ DealDamage[^\n]*ValidTgts\$ Any[^\n]*NumDmg\$ 2",
                "Adventure must deal two damage",
            ),
        ],
    ),
    (
        4,
        "bala_ged_recovery",
        "Bala Ged Recovery",
        "Astra Verdant Recall",
        [
            check(
                r"SP\$ ChangeZone[^\n]*ValidTgts\$ Card\.YouOwn[^\n]*Origin\$ Graveyard[^\n]*Destination\$ Hand",
                "Front must return an owned graveyard card to hand",
            ),
            check(
                r"^R:Event\$ Moved[^\n]*Destination\$ Battlefield",
                "Back must replace entering the battlefield",
            ),
            check(r"DB\$ Tap[^\n]*ETB\$ True", "Back must enter tapped"),
            check(r"AB\$ Mana[^\n]*Cost\$ T[^\n]*Produced\$ G", "Back must tap for green"),
        ],
    ),
    (
        4,
        "rest_in_peace",
        "Rest in Peace",
        "Astra Silent Repose",
        [
            check(
                r"^T:Mode\$ ChangesZone[^\n]*Destination\$ Battlefield", "Needs an enters trigger"
            ),
            check(
                r"DB\$ ChangeZoneAll[^\n]*Origin\$ Graveyard[^\n]*Destination\$ Exile",
                "Enters trigger must exile all graveyards",
            ),
            check(
                r"^R:Event\$ Moved[^\n]*Destination\$ Graveyard[^\n]*ValidCard\$ Card",
                "Replacement must include cards and tokens going to any graveyard",
            ),
            check(
                r"DB\$ ChangeZone[^\n]*Origin\$ All[^\n]*Destination\$ Exile[^\n]*Defined\$ ReplacedCard",
                "Replacement must exile the moved object instead",
            ),
        ],
    ),
]


def main():
    scryfall = Scryfall()
    result = []
    for tier, identifier, source_name, alias, checks in SPECS:
        raw = scryfall.http.request("GET", "/cards/named", params={"exact": source_name})
        original = Card.from_scryfall(raw)
        card = original.model_copy(deep=True)
        original_names = [f.name for f in card.faces]
        for i, face in enumerate(card.faces):
            face.name = alias + (f" Aspect {i + 1}" if len(card.faces) > 1 else "")
        for face in card.faces:
            for old, new in zip(original_names, [f.name for f in card.faces], strict=True):
                face.oracle_text = face.oracle_text.replace(old, new)
        card.name = " // ".join(f.name for f in card.faces)
        card.id = card.oracle_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, "forge-astra/benchmark/" + identifier)
        )
        card.source_url = ""
        card.set_code = f"t{tier}a"
        card.collector_number = str(len(result) + 1)
        result.append(
            {
                "id": identifier,
                "tier": tier,
                "source_name": source_name,
                "source_url": original.source_url,
                "card": card.model_dump(mode="json"),
                "checks": checks,
            }
        )
        print(identifier)
    unknown = Card.from_scryfall(
        {
            "id": "astra-unknown",
            "oracle_id": "astra-unknown",
            "set": "t5a",
            "name": "Astra Unwritten Voyager",
            "type_line": "Creature — Wizard",
            "mana_cost": "{2}{U}",
            "power": "2",
            "toughness": "3",
            "released_at": "2030-01-01",
            "keywords": ["Chronoweave"],
            "oracle_text": "Chronoweave (Whenever this creature attacks, open a parallel turn. Play that turn simultaneously with this turn, sharing permanents but tracking independent stacks and phases.)",
        }
    )
    result.append(
        {
            "id": "unsupported_chronoweave",
            "tier": 5,
            "source_name": None,
            "card": unknown.model_dump(mode="json"),
            "checks": [],
            "expected_status": "blocked",
        }
    )
    path = Path("src/forge_astra/benchmarks/cards.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    scryfall.http.close()
    print(f"Wrote {len(result)} renamed benchmark inputs")


if __name__ == "__main__":
    main()
