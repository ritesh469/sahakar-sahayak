"""P11 metrics on small hand-made examples."""

import pytest

from app.models import RetrievedChunk
from eval.metrics import (
    Evidence,
    answer_outcome,
    citation_precision,
    extract_citations,
    is_relevant,
    mrr,
    precision_at_k,
    recall_at_k,
    refusal_detected,
    refusal_type,
)


def ch(source, page=None):
    return RetrievedChunk(text="x", source=source, page_number=page)


RETRIEVED = [ch("a.pdf", 7), ch("b.pdf", 3), ch("a.pdf", 2), ch("c.pdf", None), ch("b.pdf", 9)]
GOLD = [Evidence("b.pdf", 3), Evidence("a.pdf", 2)]


def test_relevance_uses_source_and_page():
    assert is_relevant(ch("b.pdf", 3), Evidence("b.pdf", 3))
    assert is_relevant(ch("b.pdf", 2), Evidence("b.pdf", 3))  # chunk starting 1 page earlier
    assert not is_relevant(ch("b.pdf", 4), Evidence("b.pdf", 3))  # starts after the evidence
    assert not is_relevant(ch("b.pdf", 1), Evidence("b.pdf", 3))
    assert not is_relevant(ch("a.pdf", 3), Evidence("b.pdf", 3))
    assert is_relevant(ch("b.pdf", None), Evidence("b.pdf"))  # no page given = any page
    assert not is_relevant(ch("b.pdf", None), Evidence("b.pdf", 3))
    assert is_relevant({"source": "b.pdf", "page_number": 3}, Evidence("b.pdf", 3))  # dict rows


def test_recall_at_k_gold_items_are_alternatives():
    assert recall_at_k(RETRIEVED, GOLD, k=1) == 0.0
    assert recall_at_k(RETRIEVED, GOLD, k=2) == 1.0  # b.pdf p.3 found; a.pdf p.2 not needed
    assert recall_at_k(RETRIEVED, [Evidence("a.pdf", 2)], k=2) == 0.0
    assert recall_at_k(RETRIEVED, [Evidence("a.pdf", 2)], k=3) == 1.0
    assert recall_at_k(RETRIEVED, [], k=3) == 0.0


def test_precision_at_k():
    assert precision_at_k(RETRIEVED, GOLD, k=1) == 0.0
    assert precision_at_k(RETRIEVED, GOLD, k=3) == pytest.approx(2 / 3)
    assert precision_at_k(RETRIEVED, GOLD, k=5) == pytest.approx(2 / 5)


def test_mrr():
    assert mrr(RETRIEVED, GOLD) == 0.5  # first relevant at rank 2
    assert mrr(RETRIEVED, [Evidence("c.pdf")]) == pytest.approx(1 / 4)
    assert mrr(RETRIEVED, [Evidence("z.pdf")]) == 0.0
    assert mrr(RETRIEVED, [Evidence("c.pdf")], k=3) == 0.0


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        ("I could not find this information in the available documents.", "no_info"),
        ("उपलब्ध दस्तावेज़ों में यह जानकारी नहीं मिली।", "no_info"),
        ("उपलब्ध कागदपत्रांमध्ये ही माहिती आढळली नाही.", "no_info"),
        ("Yeh jaankari uplabdh documents mein nahi mili.", "no_info"),
        ("This assistant only answers questions about cooperatives and government schemes.", "out_of_domain"),
        ("हा सहाय्यक फक्त सहकार आणि शासकीय योजनांशी संबंधित प्रश्नांची उत्तरे देतो.", "out_of_domain"),
        ("PM-KISAN gives Rs 6000 per year [pmkisan_guidelines_en.pdf, p. 3].", None),
        ("The documents mention no deadline, but registration is on the portal [x.pdf, p. 2].", None),
    ],
)
def test_refusal_type(answer, kind):
    assert refusal_type(answer) == kind
    assert refusal_detected(answer) == (kind is not None)


def test_answer_outcome():
    refusal = "I could not find this information in the available documents."
    answer = "It is Rs 6000 per year [a.pdf, p. 1]."
    assert answer_outcome(True, answer) == "answered"
    assert answer_outcome(True, refusal) == "over_refusal"
    assert answer_outcome(False, refusal) == "correct_refusal"
    assert answer_outcome(False, answer) == "hallucination"


def test_citations():
    answer = "Rs 6000 [pmkisan_guidelines_en.pdf, p. 3]. Pension at 60 [pmkmy_faqs_en.pdf, p.12] and [notes.docx]."
    assert extract_citations(answer) == [
        Evidence("pmkisan_guidelines_en.pdf", 3),
        Evidence("pmkmy_faqs_en.pdf", 12),
        Evidence("notes.docx", None),
    ]
    retrieved = [ch("pmkisan_guidelines_en.pdf", 3), ch("pmkmy_faqs_en.pdf", 12)]
    assert citation_precision(answer, retrieved) == pytest.approx(2 / 3)
    assert citation_precision("no citations here", retrieved) is None


FAKE_PREMISE_FACTS = [r"6000", r"सहा हजार"]


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        # corrects the premise (12,000 -> 6,000), in Marathi with Devanagari digits and in English
        ("या योजनेत दरवर्षी ₹६,००० तीन हप्त्यांमध्ये मिळतात [pmkisan_ekyc_note_mr.pdf, p. 1].", "premise_corrected"),
        ("PM-KISAN gives Rs 6,000 a year, not 12,000 [pmkisan_ekyc_note_en.pdf, p. 1].", "premise_corrected"),
        # goes along with the false premise
        ("12,000 रुपये एप्रिल, ऑगस्ट आणि डिसेंबरमध्ये जमा होतात.", "hallucination"),
        # refusing is also safe
        ("उपलब्ध कागदपत्रांमध्ये ही माहिती आढळली नाही.", "correct_refusal"),
    ],
)
def test_fake_premise_outcome(answer, outcome):
    assert answer_outcome(False, answer, "fake_premise", FAKE_PREMISE_FACTS) == outcome


def test_premise_facts_ignored_for_other_question_types():
    # an unanswerable question answered with a number is still a hallucination
    assert answer_outcome(False, "It is Rs 6,000.", None, FAKE_PREMISE_FACTS) == "hallucination"
