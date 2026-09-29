import threading

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models import RetrievedChunk
from app.services.text_tokenizer import tokenize


class BM25Index:
    """Okapi BM25 over chunks, tokenized with the Devanagari-aware tokenizer (P8)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.documents: list[dict] = []
        self.bm25: BM25Okapi | None = None
        self._lock = threading.RLock()

    def fit(self, documents: list[dict]) -> None:
        with self._lock:
            self.documents = documents
            corpus = [tokenize(doc.get("text", "")) for doc in documents]
            # BM25Okapi divides by the corpus size / average length, so skip empty corpora
            self.bm25 = BM25Okapi(corpus, k1=self.k1, b=self.b) if any(corpus) else None

    def search(self, query: str, top_k: int = 20) -> list[RetrievedChunk]:
        """Return top-k chunks by BM25 score (chunks with score <= 0 are dropped)."""
        with self._lock:
            tokens = tokenize(query)
            if self.bm25 is None or not tokens:
                return []
            scores = self.bm25.get_scores(tokens)
            results: list[RetrievedChunk] = []
            for idx in np.argsort(scores)[::-1][:top_k]:
                score = float(scores[idx])
                if score <= 0:
                    break
                doc = self.documents[idx]
                results.append(
                    RetrievedChunk(
                        text=doc.get("text", ""),
                        source=doc.get("source", ""),
                        page_number=doc.get("page_number"),
                        score=score,
                    )
                )
            return results


class SparseVectorIndex:
    """Original TF-IDF sparse index (sklearn defaults). Kept as the baseline for the
    tokenization comparison: its token pattern splits Devanagari words (Known problem #2)."""

    def __init__(self) -> None:
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.documents: list[dict] = []
        self.matrix = None
        self._lock = threading.RLock()


    def fit(self, documents: list[dict]) -> None:
        with self._lock:
            self.documents = documents
            if not documents:
                self.matrix = None
                return

            texts = [doc.get("text", "") for doc in documents]
            try:
                self.matrix = self.vectorizer.fit_transform(texts)
            except ValueError:
                self.matrix = None
                return

            if self.matrix.shape[1] == 0:
                self.matrix = None
        

    def search(self, query: str, top_k: int = 20) -> list[RetrievedChunk]:
        """Return top-k chunks by TF-IDF cosine similarity."""
        with self._lock:
            if self.matrix is None or len(self.documents) == 0:
                return []

            query_vec = self.vectorizer.transform([query])
            similarities = cosine_similarity(query_vec, self.matrix).flatten()
            top_indices = similarities.argsort()[::-1][:top_k]

            results: list[RetrievedChunk] = []
            for idx in top_indices:
                score = float(similarities[idx])
                if score <= 0:
                    continue
                doc = self.documents[idx]
                results.append(
                    RetrievedChunk(
                        text=doc.get("text", ""),
                        source=doc.get("source", ""),
                        page_number=doc.get("page_number"),
                        score=score,
                    )
                )
            return results

def fuse_rrf(
    result_lists: list[list[RetrievedChunk]],
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Fuse multiple ranked result lists using Reciprocal Rank Fusion."""
    # A chunk is identified by source + page + text: the same text can occur in two documents
    # (e.g. a table repeated in the English and Hindi version) and both should be kept
    scores: dict[tuple, float] = {}
    meta: dict[tuple, RetrievedChunk] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            key = (chunk.source, chunk.page_number, chunk.text)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in meta:
                meta[key] = chunk

    return [
        meta[key].model_copy(update={"score": score})
        for key, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)
    ]
    