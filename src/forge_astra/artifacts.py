import json
import os
from pathlib import Path

from forge_astra.models import Card, Draft, slug
from forge_astra.scripting import deck_text


def write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


class BatchWriter:
    def __init__(self, output: Path, day: str, run_id: str):
        self.path = output / day / run_id
        self.entries: list[dict] = []

    def add(self, state: dict, commit: str, discovery: dict) -> dict:
        card = Card.model_validate(state["card"])
        set_dir = self.path / slug(card.set_code)
        identifier = slug(card.name.replace(" // ", " "))
        report_path = set_dir / "reports" / (identifier + "-" + card.fingerprint[:10] + ".json")
        report = {
            **state,
            "upstream_commit": commit,
            "discovery": discovery,
            "gameplay_tested": False,
            "set_code": card.set_code,
        }
        entry = {
            "card_key": card.key,
            "name": card.name,
            "set_code": card.set_code,
            "status": state["status"],
            "report": str(report_path.resolve()),
            "blockers": state.get("blockers", []),
            "issues": state.get("issues", []),
        }
        if state["status"] == "draft":
            script_path = set_dir / "cardsfolder" / identifier[0] / (identifier + ".txt")
            deck_path = set_dir / "decks" / (identifier + ".dck")
            write_atomic(script_path, state["script"])
            draft = Draft.model_validate(state["draft"])
            write_atomic(deck_path, deck_text(card, draft))
            write_atomic(
                set_dir / "test-plans" / (identifier + ".md"),
                f"# {card.name}\n\nGameplay testing is pending. Disable `ENFORCE_DECK_LEGALITY` in the test Forge profile.\n\n"
                + "\n".join(f"- {item}" for item in draft.test_plan)
                + "\n\nSupport cards:\n\n"
                + "\n".join(f"- {c.count} {c.name}: {c.purpose}" for c in draft.support_cards)
                + "\n",
            )
            entry.update(script=str(script_path.resolve()), deck=str(deck_path.resolve()))
        else:
            # Rejected drafts may be examined in JSON, but are never installable card files.
            report.pop("script", None)
        write_atomic(report_path, json.dumps(report, indent=2, ensure_ascii=False))
        self.entries.append(entry)
        self.flush()
        return entry

    def flush(self):
        write_atomic(
            self.path / "manifest.json", json.dumps(self.entries, indent=2, ensure_ascii=False)
        )
        for set_code in {e["set_code"] for e in self.entries}:
            entries = [e for e in self.entries if e["set_code"] == set_code]
            set_dir = self.path / slug(set_code)
            write_atomic(
                set_dir / "manifest.json", json.dumps(entries, indent=2, ensure_ascii=False)
            )
            drafts = [e for e in entries if e["status"] == "draft"]
            text = (
                f"# Add {len(drafts)} {set_code.upper()} card scripts\n\n"
                f"This batch contains only cards from set `{set_code}`. Keep it in its own pull request.\n\n"
                "Gameplay testing is pending; these are generated drafts. No pull request has been opened.\n\n"
            )
            text += "\n".join(f"- {e['name']}: {e['status']}" for e in entries) + "\n"
            write_atomic(set_dir / "PR_DRAFT.md", text)
