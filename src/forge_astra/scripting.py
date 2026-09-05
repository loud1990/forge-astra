import re
from collections import Counter

from forge_astra.corpus import Corpus, active_lines
from forge_astra.models import Card, Draft, Plan, SupportCard, normalize
from forge_astra.upstream import GAME

ALTERNATES = {
    "transform": "Transform",
    "modal_dfc": "Modal",
    "split": "Split",
    "adventure": "Adventure",
    "prepare": "Prepare",
    "flip": "Flip",
}
SINGLE_LAYOUTS = {"normal", "leveler", "saga", "class", "prototype", "mutate", "host"}
LINE_TYPES = {"A", "K", "T", "R", "S", "SVar", "AI", "DeckHints", "DeckHas", "DeckNeeds", "Text"}
COLORS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
LANDS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest", "C": "Wastes"}


def metadata_issues(card: Card) -> list[str]:
    issues = []
    if not card.oracle_complete:
        issues.append("Scryfall has not supplied complete Oracle text for every face")
    if card.layout not in SINGLE_LAYOUTS | ALTERNATES.keys():
        issues.append(f"Layout {card.layout} needs explicit layout/linkage support")
    expected = 2 if card.layout in ALTERNATES else 1
    if len(card.faces) != expected:
        issues.append(f"Expected {expected} faces for layout {card.layout}")
    for face in card.faces:
        if not face.type_line:
            issues.append(f"Missing type line for {face.name}")
        if "Creature" in face.type_line and (face.power is None or face.toughness is None):
            issues.append(f"Missing creature stats for {face.name}")
        if "Planeswalker" in face.type_line and face.loyalty is None:
            issues.append(f"Missing loyalty for {face.name}")
        if "Battle" in face.type_line and face.defense is None:
            issues.append(f"Missing defense for {face.name}")
    return issues


def plan_issues(card: Card, plan: Plan, evidence: list[dict]) -> list[str]:
    issues = []
    expected = {c["id"] for c in card.clauses()}
    ids = [c.clause_id for c in plan.clauses]
    if set(ids) != expected or len(ids) != len(expected):
        issues.append("Plan must cover every Oracle clause exactly once")
    by_id = {e["id"]: e for e in evidence}
    for clause in plan.clauses:
        if clause.needs_engine or clause.blocker:
            issues.append(f"{clause.clause_id}: {clause.blocker or 'requires engine support'}")
        grounded = False
        for citation in clause.citations:
            source = by_id.get(citation.evidence_id)
            if not source or citation.quote not in source["body"]:
                issues.append(f"{clause.clause_id}: fabricated or stale evidence citation")
                continue
            layout_marker = "AlternateMode:" + ALTERNATES.get(card.layout, "")
            layout_evidence = (
                card.layout in ALTERNATES
                and citation.quote == layout_marker
                and layout_marker in source["body"].splitlines()
            )
            if source["kind"] == "script" and (
                citation.quote in "\n".join(active_lines(source["body"])) or layout_evidence
            ):
                grounded = True
        if not grounded:
            issues.append(f"{clause.clause_id}: no executable upstream script citation")
    return issues


def assemble(card: Card, draft: Draft) -> str:
    faces = []
    for i, face in enumerate(card.faces):
        cost = " ".join(re.findall(r"\{([^}]+)\}", face.mana_cost)) or "no cost"
        lines = [
            f"Name:{face.name}",
            f"ManaCost:{cost}",
            "Types:" + face.type_line.replace(" — ", " ").replace("—", " ").strip(),
        ]
        if face.power is not None and face.toughness is not None:
            lines.append(f"PT:{face.power}/{face.toughness}")
        if face.loyalty is not None:
            lines.append("Loyalty:" + face.loyalty)
        if face.defense is not None:
            lines.append("Defense:" + face.defense)
        if face.color_indicator:
            lines.append("Colors:" + ",".join(COLORS[c] for c in face.color_indicator))
        lines.extend(draft.faces[i].lines)
        if i == 0 and card.layout in ALTERNATES:
            lines.append("AlternateMode:" + ALTERNATES[card.layout])
        lines.append("Oracle:" + face.oracle_text.replace("\n", "\\n"))
        faces.append("\n".join(lines))
    return "\n\nALTERNATE\n\n".join(faces) + "\n"


def metadata_matches(card: Card, script: str) -> bool:
    """An Oracle match must not hide corrected costs or face statistics."""
    blocks = re.split(r"(?m)^ALTERNATE\s*$", script)
    if len(blocks) != len(card.faces):
        return False
    for face, block in zip(card.faces, blocks, strict=True):
        fields = dict(
            re.findall(r"^(Name|ManaCost|Types|PT|Loyalty|Defense|Oracle):([^\n]*)", block, re.M)
        )
        cost = " ".join(re.findall(r"\{([^}]+)\}", face.mana_cost)) or "no cost"
        # Forge's ManaCostShard parser accepts both RW and R/W for one hybrid
        # shard. Preserve shard boundaries so R W remains two separate symbols.
        actual_cost = Counter(fields.get("ManaCost", "").replace("/", "").split())
        expected_cost = Counter(cost.replace("/", "").split())
        if fields.get("Name") != face.name or actual_cost != expected_cost:
            return False
        if set(fields.get("Types", "").split()) != set(face.type_line.replace("—", " ").split()):
            return False
        for key, value in [("Loyalty", face.loyalty), ("Defense", face.defense)]:
            if value is not None and fields.get(key) != value:
                return False
        if face.power is not None and fields.get("PT") != f"{face.power}/{face.toughness}":
            return False
        oracle = fields.get("Oracle", "").replace("\\n", "\n").replace(face.name, "CARDNAME")
        if normalize(oracle) != normalize(face.oracle_text.replace(face.name, "CARDNAME")):
            return False
    return True


def validate_draft(card: Card, draft: Draft, corpus: Corpus, support_pool: list[dict]) -> list[str]:
    issues = metadata_issues(card)
    if len(draft.faces) != len(card.faces):
        return [*issues, "Draft face count differs from Scryfall"]
    caps = corpus.capabilities
    reference_keys = {
        "Execute",
        "SubAbility",
        "ReplaceWith",
        "PreventionSubAbility",
        "SpellAbilities",
        "Abilities",
        "StaticAbilities",
        "Triggers",
    }
    factory = corpus.root / GAME / "ability/AbilityFactory.java"
    if factory.exists():
        match = re.search(
            r"additionalAbilityKeys\s*=\s*Lists.newArrayList\((.*?)\);", factory.read_text(), re.S
        )
        if match:
            reference_keys.update(re.findall(r'"(\w+)"', match.group(1)))
    for i, face in enumerate(draft.faces):
        svars = set()
        refs = set()
        for line in face.lines:
            if "\n" in line or "\r" in line or not line.strip():
                issues.append("Each script entry must be one nonempty line")
                continue
            kind, sep, rest = line.partition(":")
            if not sep or kind not in LINE_TYPES:
                issues.append(f"Invalid script line type: {kind}")
                continue
            if kind in {"AI", "DeckHints", "DeckHas", "DeckNeeds", "Text"}:
                # These fields use their own metadata grammar, not the ability API.
                continue
            if kind == "SVar":
                name, sep, rest = rest.partition(":")
                if not sep or not name or name in svars:
                    issues.append(f"Invalid or duplicate SVar: {name}")
                svars.add(name)
            fields = re.findall(r"(?:^|\|)\s*(\w+)\$\s*([^|]*)", rest)
            for param, count in Counter(key for key, _ in fields).items():
                if count > 1:
                    issues.append(f"Duplicate ability parameter: {param}")
            params = dict(fields)
            params = {k: v.strip() for k, v in params.items()}
            if (
                kind == "SVar"
                and params.get("Count", "").startswith("Compare ")
                and len(params["Count"].split(".", 2)) < 3
            ):
                issues.append(
                    "Count$Compare requires both true and false result branches: "
                    "Compare <value> <comparison>.<true>.<false>"
                )
            if kind == "SVar" and re.search(
                r"^CardCounters\.[A-Z0-9_]+\s+(?:GE|GT|EQ|NE|LE|LT)[+-]?\d+$",
                params.get("Count", ""),
            ):
                issues.append(
                    "Counter-count SVar contains an inline comparison: keep the count numeric "
                    "and put the threshold in SVarCompare or ConditionSVarCompare"
                )
            for param in params:
                if param not in caps["param"]:
                    issues.append(f"Unknown upstream parameter: {param}")
            for marker in ("AB", "SP", "DB"):
                if marker in params and params[marker] not in caps["api"]:
                    issues.append(f"Unknown upstream ability: {params[marker]}")
            if kind == "A" and not {"AB", "SP", "DB"}.intersection(params):
                issues.append("A line needs an ability type (AB, SP, or DB)")
            if kind == "T" and params.get("Mode") not in caps["trigger"]:
                issues.append(f"Unknown upstream trigger: {params.get('Mode')}")
            if kind == "R" and params.get("Event") not in caps["replacement"]:
                issues.append(f"Unknown upstream replacement: {params.get('Event')}")
            if kind in {"S", "SVar"} and "Mode" in params and params["Mode"] not in caps["static"]:
                issues.append(f"Unproven static mode: {params['Mode']}")
            if kind == "K":
                keyword = rest.split(":")[0]
                # Forge also has exact plaintext K: statements outside Keyword.java.
                known = any(k.casefold() == keyword.casefold() for k in caps["keyword"])
                if not known:
                    known = corpus.has_keyword_line(line)
                if not known:
                    issues.append(f"Unproven keyword: {keyword}")
            for key in reference_keys:
                if key in params:
                    refs.update(re.split(r",\s*", params[key]))
            api = next((params[k] for k in ("AB", "SP", "DB") if k in params), "")
            # A single opponent-only mill instruction cannot target its controller.
            # Keep faces with multiple target instructions outside this narrow check;
            # those require per-ability gameplay contracts.
            oracle = card.faces[i].oracle_text
            if (
                api == "Mill"
                and re.search(r"\btarget opponent mills\b", oracle, re.I)
                and len(re.findall(r"\btarget\b", oracle, re.I)) == 1
                and any(t.strip() == "Player" for t in params.get("ValidTgts", "").split(","))
            ):
                issues.append(
                    "Opponent-only mill targets all players: use an opponent-restricted target filter"
                )
            # CountersPutEffect resolves Defined through getDefinedEntities;
            # a bare validity selector does not enumerate matching permanents.
            if api == "PutCounter" and re.match(
                r"^(?:Card|Creature|Artifact|Enchantment|Land|Planeswalker|Battle|Equipment|Treasure|Permanent|Token)(?:[.,+]|$)",
                params.get("Defined", ""),
            ):
                issues.append(
                    "PutCounter Defined is a validity filter, not a defined object: "
                    "use Defined$ Valid <filter> or PutCounterAll with ValidCards$ <filter>"
                )
            if (
                api in {"Charm", "GenericChoice", "AssignGroup", "VillainousChoice", "Vote"}
                and "Choices" in params
            ):
                refs.update(re.split(r",\s*", params["Choices"]))
            if api == "RollDice" and "ResultSubAbilities" in params:
                refs.update(
                    entry.split(":")[-1].strip()
                    for entry in params["ResultSubAbilities"].split(",")
                )
            if "TokenScript" in params:
                for token in params["TokenScript"].split(","):
                    if (
                        not re.fullmatch(r"[\w-]+", token.strip())
                        or not (
                            corpus.root / "forge-gui/res/tokenscripts" / (token.strip() + ".txt")
                        ).is_file()
                    ):
                        issues.append(f"Missing upstream token script: {token}")
        for ref in sorted(refs - svars - {"None", ""}):
            issues.append(f"Face {i}: undefined SVar {ref}")
        if card.faces[i].oracle_text.strip() and not any(active_lines(line) for line in face.lines):
            issues.append(f"Face {i}: Oracle text has no executable implementation")
    allowed = {e["name"] for e in support_pool}
    counts = Counter()
    for support in draft.support_cards:
        counts[support.name] += support.count
        if support.name not in allowed or support.name in {
            card.name,
            *(f.name for f in card.faces),
        }:
            issues.append(f"Unsupported deck card: {support.name}")
    if sum(counts.values()) != 28 or any(n > 4 for n in counts.values()):
        issues.append("Test deck needs 28 support cards, at most four of each")
    return sorted(set(issues))


def balance_support(draft: Draft, support_pool: list[dict]) -> Draft:
    """Enforce deck arithmetic without spending script revisions on card counts."""
    allowed = {entry["name"] for entry in support_pool}
    if any(card.name not in allowed for card in draft.support_cards):
        return draft  # Unknown names still require model repair and cannot be exported.
    selected = {}
    for card in draft.support_cards:
        if card.name not in selected:
            selected[card.name] = card.model_copy()
        else:
            selected[card.name].count = min(4, selected[card.name].count + card.count)
    total = sum(card.count for card in selected.values())
    if total < 28:
        for card in selected.values():
            amount = min(4 - card.count, 28 - total)
            card.count += amount
            total += amount
        for entry in support_pool:
            if total == 28:
                break
            if entry["name"] not in selected:
                count = min(4, 28 - total)
                selected[entry["name"]] = SupportCard(
                    name=entry["name"],
                    count=count,
                    purpose="Additional support from the retrieved card pool; check synergy in the scenario plan.",
                )
                total += count
    if total > 28:
        for name in reversed(list(selected)):
            amount = min(selected[name].count, total - 28)
            selected[name].count -= amount
            total -= amount
            if selected[name].count == 0:
                del selected[name]
            if total == 28:
                break
    result = draft.model_copy(deep=True)
    result.support_cards = list(selected.values())
    return result


def deck_text(card: Card, draft: Draft) -> str:
    lines = ["[metadata]", "Name=Test - " + card.faces[0].name, "[Main]", "8 " + card.faces[0].name]
    counts = Counter()
    for support in draft.support_cards:
        counts[support.name.split(" // ")[0]] += support.count
    lines.extend(f"{count} {name}" for name, count in sorted(counts.items()))
    colors = card.colors or ["C"]
    for i, color in enumerate(colors):
        count = 24 // len(colors) + (i < 24 % len(colors))
        lines.append(f"{count} {LANDS[color]}")
    return "\n".join(lines) + "\n"
