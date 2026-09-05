import hashlib
import json
import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def slug(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_")) or "card"


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[\w]+", text.casefold()))


class Face(BaseModel):
    name: str
    mana_cost: str = ""
    type_line: str
    oracle_text: str = ""
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    defense: str | None = None
    color_indicator: list[str] = Field(default_factory=list)


class Card(BaseModel):
    id: str
    oracle_id: str | None = None
    name: str
    set_code: str
    collector_number: str = ""
    layout: str = "normal"
    keywords: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    released_at: date
    previewed_at: date | None = None
    source_url: str = ""
    faces: list[Face]

    @classmethod
    def from_scryfall(cls, data: dict) -> "Card":
        return cls(
            id=data["id"],
            oracle_id=data.get("oracle_id"),
            name=data["name"],
            set_code=data["set"],
            collector_number=data.get("collector_number", ""),
            layout=data.get("layout", "normal"),
            keywords=data.get("keywords", []),
            colors=data.get("color_identity", data.get("colors", [])),
            released_at=data["released_at"],
            previewed_at=(data.get("preview") or {}).get("previewed_at"),
            source_url=data.get("scryfall_uri", ""),
            faces=[Face.model_validate(f) for f in data.get("card_faces", [data])],
        )

    @property
    def key(self) -> str:
        return self.oracle_id or self.id

    @property
    def fingerprint(self) -> str:
        return digest(
            {
                "faces": [f.model_dump() for f in self.faces],
                "layout": self.layout,
                "keywords": sorted(self.keywords),
            }
        )

    def clauses(self) -> list[dict]:
        clauses = []
        for face_index, face in enumerate(self.faces):
            # Preserve costs, modal bullets, ability words, and reminders; never discard text.
            for paragraph in face.oracle_text.splitlines():
                for text in re.split(r"(?<=[.!?])\s+(?=[A-Z{])", paragraph):
                    if text.strip():
                        clauses.append(
                            {
                                "id": f"f{face_index}c{len(clauses)}",
                                "face": face_index,
                                "text": text.strip(),
                            }
                        )
        return clauses


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(StrictModel):
    evidence_id: str
    quote: str = Field(min_length=3)


class ClausePlan(StrictModel):
    clause_id: str
    explanation: str = Field(min_length=1)
    citations: list[Citation]
    needs_engine: bool
    blocker: str = ""


class Mechanic(StrictModel):
    name: str = Field(min_length=1)
    needs_engine: bool
    explanation: str


class Plan(StrictModel):
    clauses: list[ClausePlan]
    mechanics: list[Mechanic]


class ScriptFace(StrictModel):
    # Metadata is assembled from Scryfall, never supplied by the model.
    lines: list[str]


class SupportCard(StrictModel):
    name: str
    count: int = Field(ge=1, le=4)
    purpose: str


class Draft(StrictModel):
    faces: list[ScriptFace]
    support_cards: list[SupportCard]
    test_plan: list[str] = Field(min_length=1)
    lessons: list[str]


class ClauseReview(StrictModel):
    clause_id: str
    implemented: bool
    explanation: str


class Review(StrictModel):
    verdict: Literal["pass", "revise", "blocked"]
    clauses: list[ClauseReview]
    issues: list[str]
    new_mechanics: list[Mechanic]
