"""Old TF-IDF sparse search vs new BM25 (P8): tokenization and latency, for the paper.

1. Tokenization: example phrases (old vs new tokens), and over the whole corpus the share of
   Devanagari word types that sklearn's default analyzer (the old TF-IDF) splits into pieces or
   drops entirely (Known problem #2).
2. Latency per query: old = rebuild the TF-IDF index from a Qdrant scroll on every query (the
   code before P8); new = BM25 index built once and cached. Queries = the P7 smoke questions.

Writes results/sparse_comparison.json.

Usage:
    uv run --env-file .env python scripts/compare_sparse.py [--chunk-size 512] [--repeats 3]
"""

from __future__ import annotations

import app  # noqa: F401  (first: Windows DLL load order, CLAUDE.md S9)

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXAMPLES = [
    "प्रधानमंत्री फसल बीमा योजना",
    "प्रधानमंत्री किसान सम्मान निधि में किसानों को कितनी राशि मिलती है?",
    "सहकारी समितियों का पंजीकरण",
    "पुण्यश्लोक अहिल्यादेवी होळकर शेतकरी कर्जमुक्ती योजना",
    "शेतकऱ्यांना पीक विमा कसा मिळतो?",
    "PM-KISAN ka e-KYC kaise karein?",
    "Multi-State Co-operative Societies Act, 2002",
]


def _is_devanagari_word(token: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in token)


def tokenization_stats(docs: list[dict], languages: dict[str, str]) -> dict:
    from app.services.sparse_vector_service import SparseVectorIndex
    from app.services.text_tokenizer import tokenize

    old = SparseVectorIndex().vectorizer.build_analyzer()
    types: Counter = Counter()
    by_lang: dict[str, Counter] = {}
    for doc in docs:
        lang = languages.get(doc["source"], "?")
        for tok in tokenize(doc["text"], remove_stopwords=False):
            if _is_devanagari_word(tok):
                types[tok] += 1
                by_lang.setdefault(lang, Counter())[tok] += 1

    def classify(counter: Counter) -> dict:
        kept = split = dropped = 0
        kept_tok = split_tok = dropped_tok = 0
        for word, freq in counter.items():
            pieces = old(word)
            if pieces == [word]:
                kept, kept_tok = kept + 1, kept_tok + freq
            elif pieces:
                split, split_tok = split + 1, split_tok + freq
            else:
                dropped, dropped_tok = dropped + 1, dropped_tok + freq
        n, n_tok = max(kept + split + dropped, 1), max(kept_tok + split_tok + dropped_tok, 1)
        return {
            "word_types": kept + split + dropped,
            "types_intact_pct": round(100 * kept / n, 1),
            "types_split_pct": round(100 * split / n, 1),
            "types_dropped_pct": round(100 * dropped / n, 1),
            "word_occurrences": kept_tok + split_tok + dropped_tok,
            "occurrences_intact_pct": round(100 * kept_tok / n_tok, 1),
            "occurrences_split_pct": round(100 * split_tok / n_tok, 1),
            "occurrences_dropped_pct": round(100 * dropped_tok / n_tok, 1),
        }

    return {"all": classify(types), **{lang: classify(c) for lang, c in sorted(by_lang.items())}}


def _old_tfidf_search(collection: str, query: str, top_k: int):
    """The pre-P8 code path: one scroll(limit=10000) + TF-IDF fit on every query."""
    from app.services.sparse_vector_service import SparseVectorIndex
    from app.services.vector_store import get_client

    points, _ = get_client().scroll(collection_name=collection, limit=10000,
                                    with_payload=True, with_vectors=False)
    docs = [{"text": (p.payload or {}).get("text", ""), "source": (p.payload or {}).get("source", ""),
             "page_number": (p.payload or {}).get("page_number")} for p in points]
    index = SparseVectorIndex()
    index.fit(docs)
    return index.search(query, top_k=top_k), len(docs)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunk-size", type=int, default=None)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default="results/sparse_comparison.json")
    args = ap.parse_args()

    from app.services.sparse_vector_service import SparseVectorIndex
    from app.services.text_tokenizer import tokenize
    from app.services.vector_store import _scroll_all, collection_name, get_sparse_index, invalidate_sparse_cache
    from scripts.smoke_test import QUESTIONS

    collection = collection_name(args.chunk_size)
    old_analyzer = SparseVectorIndex().vectorizer.build_analyzer()

    print(f"== Tokenization examples ({collection}) ==")
    examples = []
    for text in EXAMPLES:
        row = {"text": text, "tfidf_old": old_analyzer(text), "bm25_new": tokenize(text)}
        examples.append(row)
        print(f"{text}\n  old TF-IDF : {row['tfidf_old']}\n  new BM25   : {row['bm25_new']}")

    docs = _scroll_all(collection)
    with open(ROOT / "data" / "sources.csv", encoding="utf-8-sig", newline="") as f:
        languages = {r["filename"]: r["language"] for r in csv.DictReader(f)}
    stats = tokenization_stats(docs, languages)
    print(f"\n== Devanagari words in {len(docs)} chunks: what the old TF-IDF analyzer does ==")
    print(f"{'docs':<8}{'types':>8}{'intact%':>9}{'split%':>8}{'dropped%':>10}   (occurrences: intact/split/dropped %)")
    for lang, s in stats.items():
        print(f"{lang:<8}{s['word_types']:>8}{s['types_intact_pct']:>9}{s['types_split_pct']:>8}"
              f"{s['types_dropped_pct']:>10}   {s['occurrences_intact_pct']}/{s['occurrences_split_pct']}/"
              f"{s['occurrences_dropped_pct']}")

    print(f"\n== Latency per query ({len(QUESTIONS)} smoke questions x {args.repeats}) ==")
    queries = [q[3] for q in QUESTIONS]
    old_ms, n_old_docs = [], 0
    for _ in range(args.repeats):
        for q in queries:
            t = time.perf_counter()
            _, n_old_docs = _old_tfidf_search(collection, q, top_k=20)
            old_ms.append(1000 * (time.perf_counter() - t))

    invalidate_sparse_cache(collection)
    t = time.perf_counter()
    get_sparse_index(collection, "bm25")
    build_ms = 1000 * (time.perf_counter() - t)
    new_ms = []
    for _ in range(args.repeats):
        for q in queries:
            t = time.perf_counter()
            get_sparse_index(collection, "bm25").search(q, top_k=20)
            new_ms.append(1000 * (time.perf_counter() - t))

    latency = {
        "old_tfidf_rebuild_per_query_ms": {"mean": round(statistics.fmean(old_ms), 1),
                                           "median": round(statistics.median(old_ms), 1)},
        "old_chunks_indexed": n_old_docs,
        "new_bm25_one_time_build_ms": round(build_ms, 1),
        "new_bm25_cached_query_ms": {"mean": round(statistics.fmean(new_ms), 1),
                                     "median": round(statistics.median(new_ms), 1)},
        "new_chunks_indexed": len(docs),
        "queries": len(old_ms),
    }
    print(f"old TF-IDF (rebuild every query): mean {latency['old_tfidf_rebuild_per_query_ms']['mean']} ms, "
          f"median {latency['old_tfidf_rebuild_per_query_ms']['median']} ms ({n_old_docs} chunks)")
    print(f"new BM25: one-time build {latency['new_bm25_one_time_build_ms']} ms, then per query mean "
          f"{latency['new_bm25_cached_query_ms']['mean']} ms, median {latency['new_bm25_cached_query_ms']['median']} ms "
          f"({len(docs)} chunks)")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "date": datetime.now().isoformat(timespec="seconds"), "collection": collection,
        "chunks": len(docs), "examples": examples, "devanagari_tokenization": stats,
        "latency": latency,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
