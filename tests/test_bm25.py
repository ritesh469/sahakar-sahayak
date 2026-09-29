"""P8: Devanagari-aware tokenizer, BM25 index, cached sparse index, search modes.

The TF-IDF tokens are printed (pytest -s) because the paper compares them with the new ones.
"""

import pytest

from app.config import settings
from app.models import RetrievedChunk
from app.services import rag_service, vector_store
from app.services.sparse_vector_service import BM25Index, SparseVectorIndex, fuse_rrf
from app.services.text_tokenizer import tokenize


def _tfidf_tokens(text: str) -> list[str]:
    """Tokens of the original TF-IDF baseline (sklearn default analyzer + English stopwords)."""
    return SparseVectorIndex().vectorizer.build_analyzer()(text)


def test_devanagari_words_stay_whole():
    phrase = "प्रधानमंत्री फसल बीमा योजना"
    old, new = _tfidf_tokens(phrase), tokenize(phrase)
    print(f"\nTF-IDF (old): {old}\nBM25 tokenizer (new): {new}")
    assert new == ["प्रधानमंत्री", "फसल", "बीमा", "योजना"]
    # the known problem this fixes: the old analyzer cuts words at matras/halant
    assert "बीमा" not in old and "प्रधानमंत्री" not in old


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Marathi, with ळ and a glued case ending
        ("शेतकऱ्यांना कर्जमुक्ती मिळते", ["शेतकऱ्यांना", "कर्जमुक्ती", "मिळते"]),
        # danda is punctuation; stopwords (है, की) removed
        ("योजना की राशि ₹६,००० है।", ["योजना", "राशि", "6", "000"]),
        # English: lowercase, punctuation and stopwords removed, digits kept
        ("The PM-KISAN scheme gives Rs. 6,000!", ["pm", "kisan", "scheme", "gives", "rs", "6", "000"]),
        # zero-width joiner inside a word does not split it
        ("क्‍षेत्र", ["क्षेत्र"]),
    ],
)
def test_tokenize_examples(text, expected):
    assert tokenize(text) == expected


def test_stopwords_can_be_kept():
    assert tokenize("योजना की राशि", remove_stopwords=False) == ["योजना", "की", "राशि"]


DOCS = [
    {"text": "प्रधानमंत्री फसल बीमा योजना में किसानों को बीमा सुरक्षा मिलती है", "source": "pmfby_hi.pdf", "page_number": 3},
    {"text": "प्रधानमंत्री किसान सम्मान निधि में 6000 रुपये मिलते हैं", "source": "pmkisan_hi.pdf", "page_number": 1},
    {"text": "The grain storage plan builds godowns at PACS level", "source": "grain_en.pdf", "page_number": 7},
]


def test_bm25_ranks_the_matching_hindi_chunk_first():
    index = BM25Index()
    index.fit(DOCS)
    results = index.search("फसल बीमा", top_k=3)
    assert results[0].source == "pmfby_hi.pdf" and results[0].page_number == 3
    # chunks without any query word are not returned
    assert all(r.source != "grain_en.pdf" for r in results)


def test_bm25_empty_corpus_and_empty_query():
    index = BM25Index()
    index.fit([])
    assert index.search("बीमा") == []
    index.fit(DOCS)
    assert index.search("है की") == []  # only stopwords


def test_rrf_keeps_same_text_from_different_sources():
    a = RetrievedChunk(text="same table", source="a_en.pdf", page_number=1, score=1.0)
    b = RetrievedChunk(text="same table", source="a_hi.pdf", page_number=1, score=1.0)
    fused = fuse_rrf([[a], [b]])
    assert {c.source for c in fused} == {"a_en.pdf", "a_hi.pdf"}


class _FakeQdrant:
    """scroll() with pagination, counting calls."""

    def __init__(self, n_points: int):
        self.points = [
            type("P", (), {"id": i, "payload": {"text": f"chunk {i} योजना", "source": "x.pdf", "page_number": i}})()
            for i in range(n_points)
        ]
        self.scroll_calls = 0

    def scroll(self, collection_name, limit, offset=None, **_):
        self.scroll_calls += 1
        start = offset or 0
        page = self.points[start:start + limit]
        nxt = start + limit if start + limit < len(self.points) else None
        return page, nxt


@pytest.fixture
def fake_qdrant(monkeypatch):
    fake = _FakeQdrant(2500)
    monkeypatch.setattr(vector_store, "get_client", lambda: fake)
    vector_store.invalidate_sparse_cache()
    yield fake
    vector_store.invalidate_sparse_cache()


def test_scroll_reads_every_page(fake_qdrant):
    docs = vector_store._scroll_all("coop_512", page_size=1000)
    assert len(docs) == 2500  # the old single scroll(limit=10000) had a hard cap
    assert fake_qdrant.scroll_calls == 3


def test_sparse_index_built_once_per_collection(fake_qdrant):
    for _ in range(3):
        vector_store.sparse_search("योजना", top_k=2, collection="coop_512")
    calls_after_bm25 = fake_qdrant.scroll_calls
    assert calls_after_bm25 == 3  # one build (3 pages), then cached

    vector_store.sparse_search("योजना", top_k=2, collection="coop_512", kind="tfidf")
    assert fake_qdrant.scroll_calls == calls_after_bm25 + 3  # separate index per kind

    vector_store.invalidate_sparse_cache("coop_512")
    vector_store.sparse_search("योजना", top_k=2, collection="coop_512")
    assert fake_qdrant.scroll_calls == calls_after_bm25 + 6  # rebuilt after invalidation


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"search_mode": "bm25"}, "bm25"),
        ({"search_mode": "tfidf"}, "tfidf"),
        ({"search_mode": "sparse"}, "tfidf"),  # old name of the TF-IDF mode
        ({}, "hybrid"),  # SEARCH_MODE default
        (None, "hybrid"),
    ],
)
def test_search_mode_resolution(monkeypatch, flags, expected):
    monkeypatch.setattr(settings, "search_mode", "hybrid")
    assert rag_service.search_mode(flags) == expected


def test_unknown_search_mode_rejected():
    with pytest.raises(ValueError):
        rag_service.search_mode({"search_mode": "bm42"})


def test_retrieve_bm25_mode_calls_sparse_search_with_kind(monkeypatch):
    seen = {}

    def fake_sparse(question, top_k, kind):
        seen.update(question=question, top_k=top_k, kind=kind)
        return [RetrievedChunk(text="t", source="s.pdf", page_number=2, score=3.0)]

    monkeypatch.setattr(rag_service, "sparse_search", fake_sparse)
    chunks = rag_service.retrieve("फसल बीमा", flags={"search_mode": "bm25", "top_k": 5})
    assert seen == {"question": "फसल बीमा", "top_k": 5, "kind": "bm25"}
    assert chunks[0].page_number == 2
