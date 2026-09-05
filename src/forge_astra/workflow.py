import logging
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from forge_astra.config import Settings
from forge_astra.corpus import Corpus, active_lines
from forge_astra.llm import ChatClient
from forge_astra.models import Card, Draft, Plan, Review
from forge_astra.scripting import (
    assemble,
    balance_support,
    metadata_issues,
    metadata_matches,
    plan_issues,
    validate_draft,
)
from forge_astra.scryfall import Scryfall
from forge_astra.storage import Store
from forge_astra.upstream import DOCS, GitHub

log = logging.getLogger(__name__)


class State(TypedDict, total=False):
    card: dict
    evidence: list[dict]
    searches: list[dict]
    knowledge: dict
    support_pool: list[dict]
    plan: dict
    draft: dict
    review: dict
    script: str
    blockers: list[str]
    pr_candidates: dict
    issues: list[str]
    revisions: int
    planning_revisions: int
    status: str


PLAN_TASK = """Plan the card's complete implementation. Cover each supplied clause ID exactly
once. Cite exact executable lines or substrings (A:,K:,T:,R:,S:,SVar:) from the supplied
Forge scripts; Oracle text or documentation alone is not implementation evidence.
For parenthesized reminder rules, cite the executable ability that implements them.
For behavior provided by a supported card layout, cite the exact matching
AlternateMode line (for example AlternateMode:Adventure for casting the creature
from exile after its Adventure). The app emits that line from the card's layout.
Explain each adaptation, including changed numbers, conditions, costs and targets.
Flag needs_engine when no faithful implementation exists, even for unnamed new rules.
List ALL Scryfall keywords in mechanics, plus any new named mechanics you identify.
Do not list generic implementation categories like 'mana ability' or 'damage spell'.
Existing ability words can use generic triggers if executable analogue scripts implement
their rules. Do not assume that a familiar-looking new mechanic is supported.
"""
DRAFT_TASK = """Implement the approved plan using the supplied scripts and API docs. Return
one faces entry per card face, in order. Each entry contains ONLY executable lines and
optional AI/deck hints or Text fields. Never return Name, ManaCost, Types, PT, Oracle,
Colors, Loyalty, Defense, AlternateMode or ALTERNATE: the application assembles metadata.
Reuse proven syntax, substitute CARDNAME for self-references, and define every SVar.
Each parameter can appear only once per line. Chain sequential effects through
SubAbility on successive SVar lines; repeated SubAbility keys do not create a chain.
Use existing upstream tokens; if a required token is absent, report the need in test_plan
and do not invent its path. Select exactly SEVEN distinct support_pool entries, with
count=4 for each (7 times 4 = 28 support copies), synergizing with the target. The app adds eight target copies and 24 basic
lands. Include specific gameplay assertions and edge cases for the external harness.
Lessons are tentative discoveries, never claims of tested behavior. Address all prior
lint and review issues when revising.
"""
REVIEW_TASK = """Independently review this script against every Oracle clause and upstream
evidence. Check costs, targets, zones, optionality, timing, linked abilities, SVar counts,
replacement effects, and all faces. Look for invented semantics or missing engine work,
even when syntax is valid. Verify that each cited example actually supports the claimed
adaptation. Return every clause ID exactly once. Use blocked for missing engine support,
revise for script mistakes, pass only for a complete faithful draft. Check test deck
synergy and gameplay assertions too. Static/model checks cannot establish gameplay success.
"""


class Workflow:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        corpus: Corpus,
        scryfall: Scryfall,
        github: GitHub,
        llm: ChatClient,
    ):
        self.settings, self.store, self.corpus = settings, store, corpus
        self.scryfall, self.github, self.llm = scryfall, github, llm

    def build(self):
        graph = StateGraph(State)
        for name in ("research", "plan_card", "gate", "generate", "validate", "review_card"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "research")
        graph.add_conditional_edges("research", lambda s: END if s.get("status") else "plan_card")
        graph.add_edge("plan_card", "gate")
        graph.add_conditional_edges(
            "gate",
            lambda s: (
                "plan_card"
                if s.get("status") == "replan"
                else END
                if s.get("status")
                else "generate"
            ),
        )
        graph.add_edge("generate", "validate")
        graph.add_conditional_edges("validate", lambda s: self.after_validation(s))
        graph.add_conditional_edges(
            "review_card", lambda s: "generate" if s.get("status") == "revise" else END
        )
        return graph.compile()

    def research(self, state: State) -> dict:
        card = Card.model_validate(state["card"])
        log.info("Researching %s (%s)", card.name, card.set_code)
        blockers = metadata_issues(card)
        if blockers:
            return {"status": "blocked", "blockers": blockers}
        existing = self.corpus.named(card.name)
        expected_oracle = "\n".join(f.oracle_text.replace(f.name, "CARDNAME") for f in card.faces)
        for entry in existing:
            if metadata_matches(card, entry["body"]) and (
                not expected_oracle.strip() or active_lines(entry["body"])
            ):
                return {"status": "already_upstream", "evidence": [entry], "blockers": []}
        evidence = {}
        for part in ("0-0", "1-0", "1-1", "2-0"):
            entry = self.corpus.get(f"{DOCS}/Card-scripting-API.md#{part}")
            if entry:
                evidence[entry["id"]] = entry
        searches = []
        for clause in card.clauses():
            face = card.faces[clause["face"]]
            matches, queries = self.scryfall.analogues(clause["text"], face.name)
            searches.append(
                {
                    "clause_id": clause["id"],
                    "queries": queries,
                    "matches": [
                        {"name": m["name"], "url": m.get("scryfall_uri", "")} for m in matches[:30]
                    ],
                }
            )
            found = []
            for match in matches:
                found.extend(self.corpus.named(match["name"]))
                if len(found) >= self.settings.examples_per_clause:
                    break
            found += self.corpus.search(
                clause["text"].replace(face.name, "CARDNAME"), self.settings.examples_per_clause
            )
            for entry in found[: self.settings.examples_per_clause * 2]:
                evidence[entry["id"]] = entry
            for entry in self.corpus.search(clause["text"], 2, "doc"):
                evidence[entry["id"]] = entry
        for keyword in card.keywords:
            for entry in self.corpus.mechanic_examples(keyword, 2):
                evidence[entry["id"]] = entry
        for entry in self.corpus.search("base structure mana keywords conventions", 2, "doc"):
            evidence[entry["id"]] = entry
        # Bound each example, but never silently use a truncated script as proof.
        evidence = {k: v for k, v in evidence.items() if len(v["body"]) <= 14000}
        pool = self.support_pool(card)
        return {
            "evidence": list(evidence.values()),
            "searches": searches,
            "knowledge": self.store.knowledge(" ".join(card.keywords) + " " + expected_oracle),
            "support_pool": pool,
            "revisions": 0,
            "planning_revisions": 0,
            "issues": [],
            "blockers": [],
        }

    def support_pool(self, card: Card) -> list[dict]:
        pool = {}
        queries = [
            " ".join(f.oracle_text for f in card.faces),
            " ".join(f.type_line for f in card.faces),
            "draw card",
            "destroy target",
            "add mana",
            "creature combat",
        ]
        for query in queries:
            for entry in self.corpus.search(query, 30):
                if entry["name"] == card.name:
                    continue
                costs = " ".join(re.findall(r"^ManaCost:(.+)", entry["body"], re.M))
                colored = set(re.findall(r"[WUBRG]", costs))
                if colored - set(card.colors):
                    continue
                if re.search(r"^Types:.*\bLand\b", entry["body"], re.M):
                    continue
                pool[entry["name"]] = {
                    "name": entry["name"],
                    "oracle": entry["oracle"],
                    "mana_cost": costs,
                    "path": entry["path"],
                }
        return list(pool.values())[:70]

    def context(self, state: State) -> dict:
        card = Card.model_validate(state["card"])
        return {
            "card": state["card"],
            "clauses": card.clauses(),
            "upstream_commit": self.corpus.commit,
            **{
                k: state[k]
                for k in ("evidence", "knowledge", "support_pool", "plan", "draft", "issues")
                if k in state
            },
        }

    def plan_card(self, state: State) -> dict:
        log.info(
            "Planning %s from %d evidence excerpts", state["card"]["name"], len(state["evidence"])
        )
        return {"plan": self.llm.ask(PLAN_TASK, self.context(state), Plan).model_dump()}

    def gate(self, state: State) -> dict:
        card = Card.model_validate(state["card"])
        plan = Plan.model_validate(state["plan"])
        blockers = plan_issues(card, plan, state["evidence"])
        engine_blocked = any(c.needs_engine or c.blocker for c in plan.clauses)
        candidates = {}
        declared = {m.name.casefold(): m for m in plan.mechanics}
        text = " ".join([*card.keywords, *(f.oracle_text for f in card.faces)]).casefold()
        for keyword in card.keywords:
            if keyword.casefold() not in declared:
                blockers.append(f"Plan omitted keyword {keyword}")
        relevant = {
            m.name.casefold(): {
                "name": m.name,
                "pr": None,
                "needs_engine": m.needs_engine,
                "reason": m.explanation,
            }
            for m in plan.mechanics
            if m.needs_engine or m.name.casefold() in text
        }
        for record in self.store.mechanics():
            if record["pattern"].casefold() in text or record["name"] in relevant:
                relevant.setdefault(record["name"], {"name": record["name"], "needs_engine": False})
                relevant[record["name"]].update(pr=record["pr"], reason=record["reason"])
        for item in relevant.values():
            name = item["name"]
            supported = bool(self.corpus.mechanic_examples(name))
            if not supported:
                # Ability words can be implemented by ordinary effects/triggers.
                supported = any(
                    re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", e["oracle"], re.I)
                    and active_lines(e["body"])
                    for e in state["evidence"]
                    if e["kind"] == "script"
                )
            pr_ok, pr_reason = True, ""
            if item.get("pr"):
                pr_ok, pr_reason = self.github.merged_in_snapshot(item["pr"], self.corpus.commit)
            if not supported or item.get("needs_engine") or not pr_ok:
                engine_blocked = True
                reason = (
                    pr_reason or f"{name}: {item.get('reason', 'no executable upstream evidence')}"
                )
                blockers.append(reason)
                self.store.track_mechanic(name, name, reason, item.get("pr"))
                candidates[name] = self.github.implementation_prs(name)
        if blockers and not engine_blocked:
            attempts = state.get("planning_revisions", 0)
            return {
                "issues": sorted(set(blockers)),
                "blockers": [],
                "planning_revisions": attempts + 1,
                "status": "replan" if attempts < self.settings.max_revisions else "needs_review",
            }
        return {
            "blockers": sorted(set(blockers)),
            "pr_candidates": candidates,
            "issues": [],
            "status": "blocked" if blockers else "",
        }

    def generate(self, state: State) -> dict:
        log.info("Generating %s (revision %d)", state["card"]["name"], state["revisions"])
        draft = self.llm.ask(DRAFT_TASK, self.context(state), Draft)
        pool = list(state["support_pool"])
        known = {entry["name"] for entry in pool}
        card = Card.model_validate(state["card"])
        for support in draft.support_cards:
            if support.name in known:
                continue
            for entry in self.corpus.named(support.name):
                costs = " ".join(re.findall(r"^ManaCost:(.+)", entry["body"], re.M))
                colors = set(re.findall(r"[WUBRG]", costs))
                if colors - set(card.colors) or re.search(
                    r"^Types:.*\bLand\b", entry["body"], re.M
                ):
                    continue
                pool.append(
                    {
                        "name": entry["name"],
                        "oracle": entry["oracle"],
                        "mana_cost": costs,
                        "path": entry["path"],
                    }
                )
                known.add(entry["name"])
        draft = balance_support(draft, pool)
        return {"draft": draft.model_dump(), "support_pool": pool, "status": ""}

    def validate(self, state: State) -> dict:
        card, draft = Card.model_validate(state["card"]), Draft.model_validate(state["draft"])
        issues = validate_draft(card, draft, self.corpus, state["support_pool"])
        if issues:
            exhausted = state["revisions"] >= self.settings.max_revisions
            return {
                "issues": issues,
                "revisions": state["revisions"] + 1,
                "status": "needs_review" if exhausted else "revise",
            }
        return {"issues": [], "script": assemble(card, draft), "status": ""}

    @staticmethod
    def after_validation(state: State) -> str:
        if not state.get("issues"):
            return "review_card"
        return "generate" if state["status"] == "revise" else END

    def review_card(self, state: State) -> dict:
        log.info("Reviewing %s", state["card"]["name"])
        result = self.llm.ask(
            REVIEW_TASK, {**self.context(state), "script": state["script"]}, Review, review=True
        )
        expected = {c["id"] for c in Card.model_validate(state["card"]).clauses()}
        ids = [c.clause_id for c in result.clauses]
        issues = list(result.issues)
        if set(ids) != expected or len(ids) != len(expected):
            issues.append("Review did not cover every Oracle clause exactly once")
        issues.extend(c.explanation for c in result.clauses if not c.implemented)
        missing = [m for m in result.new_mechanics if m.needs_engine]
        if result.verdict == "blocked" or missing:
            for mechanic in missing:
                self.store.track_mechanic(mechanic.name, mechanic.name, mechanic.explanation)
            return {
                "review": result.model_dump(),
                "status": "blocked",
                "script": "",
                "blockers": issues + [m.explanation for m in missing]
                or ["Reviewer found missing engine support"],
            }
        if result.verdict != "pass" or issues:
            exhausted = state["revisions"] >= self.settings.max_revisions
            return {
                "review": result.model_dump(),
                "issues": issues or ["Reviewer requested revision"],
                "revisions": state["revisions"] + 1,
                "status": "needs_review" if exhausted else "revise",
            }
        return {"review": result.model_dump(), "issues": [], "status": "draft"}
