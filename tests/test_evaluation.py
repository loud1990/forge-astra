from copy import deepcopy

from forge_astra.evaluation import assess, cases


def test_benchmarks_are_renamed_and_span_five_tiers():
    fixtures = cases()
    assert {c["tier"] for c in fixtures} == {1, 2, 3, 4, 5}
    for case in fixtures:
        if case.get("source_name"):
            assert case["source_name"] not in case["card"]["name"]
        assert not case["card"]["source_url"]
        assert all(face["name"].startswith("Astra") for face in case["card"]["faces"])


def test_damage_check_accepts_reordered_parameters_but_rejects_wrong_amount():
    case = next(c for c in cases() if c["id"] == "lightning_bolt")
    state = {
        "status": "draft",
        "script": "Name:Astra Ember Lance\nA:SP$ DealDamage | NumDmg$ 3 | ValidTgts$ Any\n",
    }
    assert assess(case, state) == []
    wrong = {**state, "script": state["script"].replace("NumDmg$ 3", "NumDmg$ 2")}
    assert assess(case, wrong)
    wrong["script"] += "Oracle:A:SP$ DealDamage | ValidTgts$ Any | NumDmg$ 3\n"
    assert assess(case, wrong)


def test_missing_loyalty_ability_is_flagged():
    case = next(c for c in cases() if c["id"] == "jace_beleren")
    state = {
        "status": "draft",
        "script": "Name:Astra Memory Keeper\n"
        "A:AB$ Draw | Cost$ AddCounter<2/LOYALTY> | Defined$ Player | Planeswalker$ True\n"
        "A:AB$ Draw | Cost$ SubCounter<1/LOYALTY> | ValidTgts$ Player | Planeswalker$ True\n",
    }
    assert "Needs three separate loyalty abilities" in assess(case, state)
    assert "-10 must mill twenty" in assess(case, state)


def test_unsupported_case_requires_blocking_without_script():
    case = deepcopy(next(c for c in cases() if c["tier"] == 5))
    assert assess(case, {"status": "blocked"}) == []
    assert assess(case, {"status": "draft", "script": "K:Chronoweave"})
