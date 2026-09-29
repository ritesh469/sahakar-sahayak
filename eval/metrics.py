"""Retrieval + answer metrics for the cooperative / scheme evaluation (P11).

Relevance: a retrieved chunk is relevant to a gold evidence item when it comes from the same
source file and, if the item gives a page, the chunk starts on that page or up to
`page_tolerance` pages before it (a chunk's page_number is the page it STARTS on, so a chunk
starting one page earlier can still contain the evidence).

Gold evidence items of one question are ALTERNATIVE places where the same answer is written
(e.g. the English and the Hindi version of a policy), so recall@k is per question: 1 if any
answer-bearing chunk is in the top-k, else 0; averaged over questions it is the share of
questions whose evidence was retrieved.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.security.system_prompt import OUT_OF_DOMAIN_MESSAGES, REFUSAL_MESSAGES


@dataclass(frozen=True)
class Evidence:
    source: str
    page: int | None = None


def _chunk_source_page(chunk) -> tuple[str, int | None]:
    if isinstance(chunk, dict):
        return chunk.get("source", ""), chunk.get("page_number")
    return getattr(chunk, "source", ""), getattr(chunk, "page_number", None)


def is_relevant(chunk, evidence: Evidence, page_tolerance: int = 1) -> bool:
    source, page = _chunk_source_page(chunk)
    if source != evidence.source:
        return False
    if evidence.page is None:
        return True
    return page is not None and evidence.page - page_tolerance <= page <= evidence.page


def _relevance_flags(chunks: Sequence, gold: Sequence[Evidence], k: int, tol: int) -> list[bool]:
    return [any(is_relevant(c, e, tol) for e in gold) for c in list(chunks)[:k]]


def recall_at_k(chunks: Sequence, gold: Sequence[Evidence], k: int, page_tolerance: int = 1) -> float:
    """1.0 if an answer-bearing chunk (any gold alternative) is in the top-k, else 0.0."""
    return float(any(_relevance_flags(chunks, gold, k, page_tolerance)))


def precision_at_k(chunks: Sequence, gold: Sequence[Evidence], k: int, page_tolerance: int = 1) -> float:
    """Share of the top-k chunks that are relevant (divides by k, the usual IR definition)."""
    if k <= 0:
        return 0.0
    return sum(_relevance_flags(chunks, gold, k, page_tolerance)) / k


def mrr(chunks: Sequence, gold: Sequence[Evidence], k: int | None = None, page_tolerance: int = 1) -> float:
    """Reciprocal rank of the first relevant chunk (0 if none in the top-k)."""
    limit = len(chunks) if k is None else k
    for rank, rel in enumerate(_relevance_flags(chunks, gold, limit, page_tolerance), start=1):
        if rel:
            return 1.0 / rank
    return 0.0


# --- refusals -----------------------------------------------------------------------------

# Core phrases of the fixed refusal sentences (system_prompt.py); matching on the core keeps
# detection robust to punctuation or a trailing citation the model may add
_NO_INFO_PHRASES = [
    "could not find this information",
    "यह जानकारी नहीं मिली",
    "माहिती आढळली नाही",
    "jaankari uplabdh documents mein nahi mili",
    "jankari uplabdh documents mein nahi mili",
    *REFUSAL_MESSAGES.values(),
]
_OOD_PHRASES = [
    "only answers questions about cooperatives",
    "सरकारी योजनाओं से जुड़े सवालों का जवाब देता",
    "शासकीय योजनांशी संबंधित प्रश्नांची उत्तरे देतो",
    "sarkari yojanaon se jude sawaalon ka jawab deta",
    *OUT_OF_DOMAIN_MESSAGES.values(),
]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def refusal_type(answer: str) -> str | None:
    """'no_info' (context lacks the answer), 'out_of_domain', or None (a real answer)."""
    a = _norm(answer)
    if any(_norm(p) in a for p in _OOD_PHRASES):
        return "out_of_domain"
    if any(_norm(p) in a for p in _NO_INFO_PHRASES):
        return "no_info"
    return None


def refusal_detected(answer: str) -> bool:
    return refusal_type(answer) is not None


def answer_outcome(should_answer: bool, answer: str) -> str:
    """Hallucination bookkeeping for one question.

    should_answer=True  (answerable):            answered -> 'answered', refused -> 'over_refusal'
    should_answer=False (unanswerable/adversarial): refused -> 'correct_refusal',
                                                    answered -> 'hallucination'
    """
    refused = refusal_detected(answer)
    if should_answer:
        return "over_refusal" if refused else "answered"
    return "correct_refusal" if refused else "hallucination"


# --- citations ------------------------------------------------------------------------------

_CITATION = re.compile(r"\[([^\[\]]+?\.(?:pdf|docx|html?|txt|md))(?:\s*,\s*p\.?\s*(\d+))?[^\]]*\]", re.I)


def extract_citations(answer: str) -> list[Evidence]:
    """[file.pdf, p. 3] / [file.pdf] citations in an answer."""
    return [Evidence(m.group(1).strip(), int(m.group(2)) if m.group(2) else None)
            for m in _CITATION.finditer(answer)]


def citation_precision(answer: str, retrieved: Iterable) -> float | None:
    """Share of cited sources that were actually in the retrieved context (None = no citation)."""
    cites = extract_citations(answer)
    if not cites:
        return None
    sources = {_chunk_source_page(c)[0] for c in retrieved}
    return sum(1 for c in cites if c.source in sources) / len(cites)
