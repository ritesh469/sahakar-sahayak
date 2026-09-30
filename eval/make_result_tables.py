"""P13: experiment tables for the paper, built only from results/summary.csv and results/raw/*.csv.

Writes (a table is skipped, with a message, while its runs are missing):
  results/tokenizer_results.csv       P8     old TF-IDF analyzer on Devanagari words (from sparse_comparison.json)
  results/chunking_results.csv        Exp 1  chunk size 256 / 512 / 1024 (hybrid + rerank)
  results/retrieval_results.csv       Exp 2  bm25 / tfidf / dense / hybrid (+ dense and hybrid with rerank)
  results/script_match_results.csv    Exp 2  same split by "is the answer document in the question's script?"
  results/reranking_results.csv       Exp 3  rerank off vs on (retrieval pairs + answer quality)
  results/multilingual_results.csv    Exp 4  best config, per language
  results/hallucination_results.csv   Exp 5  best config, per question type / adversarial kind / language
  results/advanced_rag_results.csv    Exp 6  HyDE / CRAG / Self-RAG (both prompts) vs baseline, English
  results/significance.csv            paired sign test (per question) for the key comparisons

Every row carries the config, run date, question count and model names. No number is typed in by
hand: rerun this script after new runs (the latest run of each config is used).

    uv run python eval/make_result_tables.py
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

import yaml
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
LANGS = ["en", "hi", "mr", "hinglish"]
BEST_CONFIG = "exp3_hybrid_rerank"  # Exp 4 / Exp 5 are splits of this run

RUN_COLS = ["config", "date", "questions", "raw_file"]
MODEL_COLS = ["llm_answer", "llm_grader", "embedding_model", "reranker_model"]
RETRIEVAL_COLS = ["recall@1", "recall@3", "recall@5", "precision@5", "mrr"]
RAGAS_COLS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
ANSWER_COLS = ["language_match", "over_refusal_rate", "hallucination_rate", *RAGAS_COLS]

# Devanagari questions (hi, mr) vs Latin-script questions (en, Hinglish)
SCRIPT = {"en": "latin", "hinglish": "latin", "hi": "devanagari", "mr": "devanagari"}
DOC_SCRIPTS = {"en": {"latin"}, "hi": {"devanagari"}, "mr": {"devanagari"},
               "en+hi": {"latin", "devanagari"}}


# ---------- loading ----------

def load_summary(path: Path) -> dict[str, dict]:
    """Latest summary row per config (ISO dates sort as strings)."""
    if not path.exists():
        sys.exit(f"{path} not found: run eval/run_experiment.py first")
    latest: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["config"] not in latest or row["date"] > latest[row["config"]]["date"]:
                latest[row["config"]] = row
    return latest


def load_raw(summary_row: dict) -> list[dict]:
    with (ROOT / summary_row["raw_file"]).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_script_match(questions: Path, sources: Path) -> dict[str, bool]:
    """Question id -> True if some relevant document is written in the question's script."""
    with sources.open(encoding="utf-8-sig", newline="") as f:
        doc_lang = {r["filename"]: r["language"] for r in csv.DictReader(f)}
    match = {}
    for q in yaml.safe_load(questions.read_text(encoding="utf-8")):
        scripts = set().union(*(DOC_SCRIPTS.get(doc_lang.get(d["source"], ""), set())
                                for d in q.get("relevant_documents") or []))
        match[q["id"]] = SCRIPT[q["language"]] in scripts
    return match


# ---------- helpers ----------

def _f(value) -> float | None:
    return None if value in (None, "") else float(value)


def _mean(values) -> float | None:
    vals = [v for v in (_f(x) for x in values) if v is not None]
    return round(statistics.fmean(vals), 4) if vals else None


def _share(rows: list[dict], outcome: str) -> float | None:
    return round(sum(r["outcome"] == outcome for r in rows) / len(rows), 4) if rows else None


def pick(row: dict, cols: list[str], prefix: str = "") -> dict:
    return {c: row.get(prefix + c, "") for c in cols}


def write(name: str, rows: list[dict]) -> None:
    path = RESULTS / name
    if not rows:
        print(f"skip {name}: its runs are not in results/summary.csv yet")
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.relative_to(ROOT).as_posix()} ({len(rows)} rows)")


def method(row: dict) -> str:
    return row["search_mode"] + (" + rerank" if row["rerank"] == "True" else "")


def answer_metrics(rows: list[dict]) -> dict:
    """Outcome rates from raw rows (rows with an error are left out and counted)."""
    ok = [r for r in rows if not r.get("error")]
    ans = [r for r in ok if r["type"] == "answerable"]
    not_ans = [r for r in ok if r["type"] != "answerable"]
    unans = [r for r in ok if r["type"] == "unanswerable"]
    return {
        "n": len(ok), "errors": len(rows) - len(ok),
        "recall@5": _mean(r["recall@5"] for r in ans), "mrr": _mean(r["mrr"] for r in ans),
        "answered_rate": _share(ans, "answered"), "over_refusal_rate": _share(ans, "over_refusal"),
        "refusal_rate_unanswerable": _share(unans, "correct_refusal"),
        "hallucination_rate": _share(not_ans, "hallucination"),
        "language_match": _mean(r["language_match"] for r in ok),
        "citation_rate": _mean(r["has_citation"] for r in ans if r["outcome"] == "answered"),
        "generation_latency_mean_s": _mean(r["generation_latency_s"] for r in ok),
        "total_latency_mean_s": _mean(r["total_latency_s"] for r in ok),
        "llm_tokens_mean": _mean(r["llm_tokens"] for r in ok),
    }


# ---------- tables ----------

def chunking(summ: dict) -> list[dict]:
    out = []
    for cfg in ("exp1_chunk_256", "exp1_chunk_512", "exp1_chunk_1024"):
        if cfg not in summ:
            continue
        r = summ[cfg]
        ingest_path = RESULTS / f"ingestion_{r['chunk_size']}.json"
        ingest = json.loads(ingest_path.read_text(encoding="utf-8")) if ingest_path.exists() else {}
        out.append({
            **pick(r, RUN_COLS), "experiment": "exp1_chunk_size", "chunk_size": r["chunk_size"],
            "method": method(r), "chunks": ingest.get("chunks", ""),
            "avg_chunk_tokens": ingest.get("avg_chunk_tokens", ""),
            **pick(r, RETRIEVAL_COLS), "retrieval_latency_mean_s": r["retrieval_latency_mean_s"],
            **{f"{lang}_{m}": r[f"{lang}_{m}"] for lang in LANGS for m in ("n", "recall@5", "mrr")},
            **pick(r, MODEL_COLS),
        })
    return out


def tokenizer() -> list[dict]:
    """Old TF-IDF analyzer on Devanagari words (scripts/compare_sparse.py, P8) as a table."""
    path = RESULTS / "sparse_comparison.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{"date": data["date"], "collection": data["collection"], "chunks": data["chunks"],
             "document_language": lang, **stats,
             "old_tfidf_query_ms_mean": data["latency"]["old_tfidf_rebuild_per_query_ms"]["mean"],
             "new_bm25_query_ms_mean": data["latency"]["new_bm25_cached_query_ms"]["mean"],
             "latency_queries": data["latency"]["queries"]}
            for lang, stats in data["devanagari_tokenization"].items()]


RETRIEVAL_CONFIGS = ["exp2_tfidf", "exp2_bm25", "exp2_dense", "exp2_hybrid",
                     "exp2_dense_rerank", "exp1_chunk_512"]


def retrieval(summ: dict) -> list[dict]:
    out = []
    for cfg in RETRIEVAL_CONFIGS:
        if cfg not in summ:
            continue
        r = summ[cfg]
        out.append({
            **pick(r, RUN_COLS), "experiment": "exp2_retrieval", "method": method(r),
            "chunk_size": r["chunk_size"], **pick(r, RETRIEVAL_COLS),
            "retrieval_latency_mean_s": r["retrieval_latency_mean_s"],
            **{f"{lang}_{m}": r[f"{lang}_{m}"] for lang in LANGS for m in ("n", "recall@5", "mrr")},
            **pick(r, MODEL_COLS),
        })
    return out


def script_match(summ: dict, match: dict[str, bool]) -> list[dict]:
    """Lexical search can only match words of the same script: split recall by that."""
    out = []
    for cfg in RETRIEVAL_CONFIGS:
        if cfg not in summ:
            continue
        r = summ[cfg]
        rows = [x for x in load_raw(r) if x["type"] == "answerable" and not x.get("error")]
        for lang in LANGS:
            for same in (True, False):
                sub = [x for x in rows if x["language"] == lang and match.get(x["id"]) is same]
                if not sub:
                    continue
                out.append({
                    **pick(r, ["config", "date", "raw_file"]), "method": method(r), "language": lang,
                    "answer_doc_in_question_script": same, "n": len(sub),
                    "recall@5": _mean(x["recall@5"] for x in sub), "mrr": _mean(x["mrr"] for x in sub),
                    **pick(r, MODEL_COLS),
                })
    return out


RERANK_PAIRS = [("dense (retrieval only)", "exp2_dense", "exp2_dense_rerank"),
                ("hybrid (retrieval only)", "exp2_hybrid", "exp1_chunk_512"),
                ("hybrid (answers + Ragas)", "exp3_hybrid", "exp3_hybrid_rerank")]


def reranking(summ: dict) -> list[dict]:
    out = []
    for pair, *cfgs in RERANK_PAIRS:
        for cfg in cfgs:
            if cfg not in summ:
                continue
            r = summ[cfg]
            ragas_n = sum(x.get("faithfulness") not in (None, "") for x in load_raw(r))
            out.append({
                **pick(r, RUN_COLS), "experiment": "exp3_reranking", "pair": pair,
                "method": method(r), "rerank": r["rerank"], **pick(r, RETRIEVAL_COLS),
                **pick(r, [*ANSWER_COLS, "refusal_rate_unanswerable"]), "ragas_n": ragas_n,
                **pick(r, ["retrieval_latency_mean_s", "generation_latency_mean_s",
                           "total_latency_mean_s"]),
                **pick(r, MODEL_COLS),
            })
    return out


def multilingual(summ: dict) -> list[dict]:
    if BEST_CONFIG not in summ:
        return []
    r = summ[BEST_CONFIG]
    out = [{**pick(r, RUN_COLS), "experiment": "exp4_language", "language": "all", "n": r["n"],
            **pick(r, RETRIEVAL_COLS), **pick(r, ANSWER_COLS), **pick(r, MODEL_COLS)}]
    for lang in LANGS:
        out.append({**pick(r, RUN_COLS), "experiment": "exp4_language", "language": lang,
                    "n": r[f"{lang}_n"], **pick(r, RETRIEVAL_COLS, f"{lang}_"),
                    **pick(r, ANSWER_COLS, f"{lang}_"), **pick(r, MODEL_COLS)})
    return out


def hallucination(summ: dict) -> list[dict]:
    if BEST_CONFIG not in summ:
        return []
    r = summ[BEST_CONFIG]
    raw = load_raw(r)
    groups = [("answerable", None, None), ("unanswerable", None, None), ("adversarial", None, None)]
    groups += [("adversarial", kind, None) for kind in ("injection", "fake_premise", "out_of_domain")]
    groups += [(t, None, lang) for t in ("answerable", "unanswerable", "adversarial") for lang in LANGS]
    out = []
    for qtype, kind, lang in groups:
        sub = [x for x in raw if x["type"] == qtype
               and (kind is None or x["adversarial_kind"] == kind)
               and (lang is None or x["language"] == lang)]
        ok = [x for x in sub if not x.get("error")]
        out.append({
            **pick(r, ["config", "date", "raw_file"]), "experiment": "exp5_hallucination",
            "type": qtype, "adversarial_kind": kind or "all", "language": lang or "all",
            "n": len(ok), "errors": len(sub) - len(ok),
            "answered_rate": _share(ok, "answered"), "over_refusal_rate": _share(ok, "over_refusal"),
            "refusal_rate": _share(ok, "correct_refusal"),
            "premise_corrected_rate": _share(ok, "premise_corrected"),
            "hallucination_rate": _share(ok, "hallucination"),
            **pick(r, MODEL_COLS),
        })
    return out


ADVANCED = [("baseline (hybrid + rerank)", BEST_CONFIG), ("HyDE", "exp6_hyde"), ("CRAG", "exp6_crag"),
            ("Self-RAG, refusal-aware prompt", "exp6_selfrag"),
            ("Self-RAG, original prompt", "exp6_selfrag_original")]


def advanced(summ: dict) -> list[dict]:
    if not any(cfg in summ for _, cfg in ADVANCED[1:]):
        return []
    out = []
    for feature, cfg in ADVANCED:
        if cfg not in summ:
            continue
        r = summ[cfg]
        rows = [x for x in load_raw(r) if x["language"] == "en"]  # Exp 6 runs are English only
        out.append({**pick(r, ["config", "date", "raw_file"]), "experiment": "exp6_advanced_rag",
                    "feature": feature, "language": "en", **answer_metrics(rows),
                    **pick(r, MODEL_COLS)})
    return out


SIGNIFICANCE_PAIRS = [
    ("chunk 256 vs 512", "exp1_chunk_256", "exp1_chunk_512"),
    ("chunk 512 vs 1024", "exp1_chunk_512", "exp1_chunk_1024"),
    ("tfidf vs bm25", "exp2_tfidf", "exp2_bm25"),
    ("bm25 vs dense", "exp2_bm25", "exp2_dense"),
    ("dense vs hybrid", "exp2_dense", "exp2_hybrid"),
    ("dense: rerank off vs on", "exp2_dense", "exp2_dense_rerank"),
    ("hybrid: rerank off vs on", "exp2_hybrid", "exp1_chunk_512"),
    ("dense + rerank vs hybrid + rerank", "exp2_dense_rerank", "exp1_chunk_512"),
]


def significance(summ: dict) -> list[dict]:
    """Two-sided sign test on per-question scores (ties dropped). The 4 language versions of a
    question share a base_id, so they are not fully independent: read p as indicative."""
    out = []
    for label, a, b in SIGNIFICANCE_PAIRS:
        if a not in summ or b not in summ:
            continue
        ra = {x["id"]: x for x in load_raw(summ[a]) if x["type"] == "answerable" and not x.get("error")}
        rb = {x["id"]: x for x in load_raw(summ[b]) if x["type"] == "answerable" and not x.get("error")}
        for lang in ["all", *LANGS]:
            ids = [i for i in ra if i in rb and (lang == "all" or ra[i]["language"] == lang)]
            for metric in ("recall@5", "mrr"):
                va = [float(ra[i][metric]) for i in ids]
                vb = [float(rb[i][metric]) for i in ids]
                b_better = sum(y > x for x, y in zip(va, vb))
                a_better = sum(x > y for x, y in zip(va, vb))
                n = a_better + b_better
                out.append({
                    "comparison": label, "config_a": a, "config_b": b, "date_a": summ[a]["date"],
                    "date_b": summ[b]["date"], "language": lang, "metric": metric, "n_paired": len(ids),
                    "mean_a": _mean(va), "mean_b": _mean(vb), "b_better": b_better,
                    "a_better": a_better, "ties": len(ids) - n,
                    "sign_test_p": round(binomtest(b_better, n, 0.5).pvalue, 4) if n else 1.0,
                })
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Build the paper's result tables from results/")
    ap.add_argument("--summary", default=str(RESULTS / "summary.csv"))
    ap.add_argument("--questions", default=str(ROOT / "eval" / "coop_questions.yaml"))
    ap.add_argument("--sources", default=str(ROOT / "data" / "sources.csv"))
    args = ap.parse_args()

    summ = load_summary(Path(args.summary))
    match = load_script_match(Path(args.questions), Path(args.sources))
    write("tokenizer_results.csv", tokenizer())
    write("chunking_results.csv", chunking(summ))
    write("retrieval_results.csv", retrieval(summ))
    write("script_match_results.csv", script_match(summ, match))
    write("reranking_results.csv", reranking(summ))
    write("multilingual_results.csv", multilingual(summ))
    write("hallucination_results.csv", hallucination(summ))
    write("advanced_rag_results.csv", advanced(summ))
    write("significance.csv", significance(summ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
