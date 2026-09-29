from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


INTENT = Literal["rag", "sql", "hybrid", "web_fallback"]
FEATURE = Literal[
    "baseline",
    "sparse",
    "dense",
    "hybrid",
    "rerank",
    "hyde",
    "crag",
    "self_rag",
    "sql",
    "hybrid_rag_sql",
    "security",
    "wild",
]

class Golden(BaseModel):
    id: str = Field(..., pattern=r"^q-\d{3}$")
    question: str = Field(..., min_length=1)
    intent: INTENT
    golden_sources: list[str] = Field(..., min_length=1)
    golden_answer_keywords: list[str] = Field(..., min_length=1)
    demonstrates_feature: FEATURE
    expected_baseline: Literal["pass", "fail"]
    expected_with_feature: Literal["pass"]
    notes: str
    forbidden_keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_expected_with_feature(self) -> "Golden":
        """Ensure expected_with_feature is always 'pass'."""
        if self.expected_with_feature != "pass":
            raise ValueError("expected_with_feature must be 'pass'")
        return self


def load_goldens(path: str | Path) -> list[Golden]:
    
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected YAML root to be a list, got {type(raw).__name__}")

    goldens = [Golden.model_validate(entry) for entry in raw]

    ids = [g.id for g in goldens]
    if len(ids) != len(set(ids)):
        duplicates = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"Duplicate golden IDs found: {duplicates}")

    # Warn (don't fail) if some feature categories have no entries.
    # Not every feature needs eval goldens — e.g. dense/sparse/security are
    # demo-only and intentionally excluded from the eval-progression set.
    present_features = {g.demonstrates_feature for g in goldens}
    all_features = set(FEATURE.__args__)  # type: ignore[attr-defined]
    missing = all_features - present_features
    if missing:
        import warnings
        warnings.warn(f"No golden entries for features: {missing} (OK if demo-only)")

    return goldens

# ---------------------------------------------------------------------------------------------
# Cooperative / government-scheme evaluation set (P10): eval/coop_questions.yaml
# ---------------------------------------------------------------------------------------------

LANGUAGE = Literal["en", "hi", "mr", "hinglish"]
QUESTION_TYPE = Literal["answerable", "unanswerable", "adversarial"]
ADVERSARIAL_KIND = Literal["injection", "fake_premise", "out_of_domain"]


class EvidenceRef(BaseModel):
    """Where the answer is written: file in seed/docs/true_data and (for PDFs) the page."""

    source: str = Field(..., min_length=1)
    page: int | None = Field(default=None, ge=1)


class CoopGolden(BaseModel):
    """One evaluation question.

    Translations of the same question share a base_id and the same relevant_documents, so
    results can be compared across languages. answerable questions need the expected answer,
    the exact supporting text (copied from the document) and where it is.
    """

    id: str = Field(..., pattern=r"^[a-z]+-\d{3}-(en|hi|mr|hinglish)$")
    base_id: str = Field(..., pattern=r"^[a-z]+-\d{3}$")
    language: LANGUAGE
    type: QUESTION_TYPE
    adversarial_kind: ADVERSARIAL_KIND | None = None
    question: str = Field(..., min_length=3)
    expected_answer: str = ""
    supporting_text: str = ""
    relevant_documents: list[EvidenceRef] = Field(default_factory=list)
    # fake_premise only: regexes of the correct fact; an answer that states it corrects the
    # premise ("PM-KISAN gives 6000, not 12000") instead of hallucinating along with it
    correct_facts: list[str] = Field(default_factory=list)
    verified: bool = False  # True once a human checked the answer (and translation)
    notes: str = ""

    @property
    def should_answer(self) -> bool:
        return self.type == "answerable"

    @model_validator(mode="after")
    def check_fields_by_type(self) -> "CoopGolden":
        if not self.id.startswith(self.base_id + "-") or not self.id.endswith("-" + self.language):
            raise ValueError(f"{self.id}: id must be '<base_id>-<language>'")
        if self.type == "answerable":
            if not self.relevant_documents:
                raise ValueError(f"{self.id}: answerable question needs relevant_documents")
            if not self.expected_answer or not self.supporting_text:
                raise ValueError(f"{self.id}: answerable question needs expected_answer and supporting_text")
        if self.type == "adversarial" and self.adversarial_kind is None:
            raise ValueError(f"{self.id}: adversarial question needs adversarial_kind")
        if self.type != "adversarial" and self.adversarial_kind is not None:
            raise ValueError(f"{self.id}: adversarial_kind is only for adversarial questions")
        if self.adversarial_kind == "fake_premise" and not self.correct_facts:
            raise ValueError(f"{self.id}: fake_premise question needs correct_facts")
        return self


def load_coop_goldens(path: str | Path) -> list[CoopGolden]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected YAML root to be a list, got {type(raw).__name__}")
    goldens = [CoopGolden.model_validate(entry) for entry in raw]

    ids = [g.id for g in goldens]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate question ids: {sorted(duplicates)}")

    # Translations must point at the same evidence and have the same type
    by_base: dict[str, CoopGolden] = {}
    for g in goldens:
        first = by_base.setdefault(g.base_id, g)
        if (g.type, g.relevant_documents) != (first.type, first.relevant_documents):
            raise ValueError(f"{g.id}: type/relevant_documents differ from {first.id} (same base_id)")
    return goldens
