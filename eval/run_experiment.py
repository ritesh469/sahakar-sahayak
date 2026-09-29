"""Experiment runner (P11): one config x the evaluation questions.

Writes one row per question to results/raw/<config>_<timestamp>.csv (appended as it goes, so
a crash or a Groq rate limit does not lose finished questions; --resume continues a file) and
one aggregate row per run to results/summary.csv (overall + per language).

Config YAML (configs/*.yaml):
    name: exp2_bm25
    chunk_size: 512
    search_mode: bm25        # dense | bm25 | tfidf | hybrid
    top_k: 5
    rerank: false
    hyde: false
    crag: false
    self_rag: false
    generate: true           # false = retrieval metrics only, no LLM call (answerable only)
    ragas: false             # Ragas on a language-balanced subset of answerable questions
    ragas_limit: 40
    languages: [en]          # optional: only these question languages
    question_types: [...]    # optional: only these types (answerable / unanswerable / adversarial)
    answerable_sample: 20    # optional: only N answerable base_ids (evenly spread over the file,
                             # all their languages); unanswerable/adversarial stay complete

Groq free tier has a tokens-per-DAY budget per model. When it is used up the run stops (exit
code 3) without a summary row; run the printed --resume command the next day.

Usage:
    uv run --env-file .env python eval/run_experiment.py --config configs/exp2_bm25.yaml
        [--questions eval/coop_questions.yaml] [--no-ragas] [--limit N] [--resume results/raw/x.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import (  # noqa: E402
    Evidence,
    answer_outcome,
    citation_precision,
    extract_citations,
    mrr,
    precision_at_k,
    recall_at_k,
    refusal_type,
)

LANGS = ["en", "hi", "mr", "hinglish"]
RETRIEVAL_KS = (1, 3, 5)
RAGAS_METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
RAW_FIELDS = [
    "id", "base_id", "language", "type", "adversarial_kind", "question",
    "retrieved", *[f"recall@{k}" for k in RETRIEVAL_KS], "precision@5", "mrr",
    "retrieval_latency_s", "generation_latency_s", "total_latency_s",
    "answer", "refusal_type", "outcome", "has_citation", "citation_precision",
    "answer_language", "language_match", "llm_tokens", *RAGAS_METRICS, "error",
]


class DailyLimitReached(RuntimeError):
    """Groq tokens/requests-per-day limit: waiting minutes does not help, resume tomorrow."""


def _is_daily_limit(message: str) -> bool:
    m = message.lower()
    return "per day" in m or "(tpd)" in m or "(rpd)" in m


def load_config(path: str) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defaults = {"chunk_size": 512, "search_mode": "hybrid", "top_k": 5, "rerank": False,
                "hyde": False, "crag": False, "self_rag": False, "generate": True,
                "ragas": False, "ragas_limit": 40}
    cfg = {**defaults, **cfg}
    cfg.setdefault("name", Path(path).stem)
    return cfg


def with_rate_limit_retry(fn, *args, tries: int = 12, wait_s: float = 20.0, **kwargs):
    """Groq free tier: tokens/min limits. The SDK already retries; this waits longer."""
    for attempt in range(tries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if _is_daily_limit(str(exc)):
                raise DailyLimitReached(str(exc)[:300]) from exc
            if "rate" not in str(exc).lower() and "429" not in str(exc):
                raise
            if attempt == tries - 1:
                raise
            print(f"    rate limited, waiting {wait_s:.0f}s ({attempt + 1}/{tries})", flush=True)
            time.sleep(wait_s)


def run_question(g, cfg: dict) -> dict:
    from app.services.language import detect_language
    from app.services.llm_service import STATS
    from app.services.rag_service import _generate, retrieve

    errors_before, tokens_before = STATS["errors"], sum(STATS["tokens"].values())

    flags = {
        "top_k": cfg["top_k"], "search_mode": cfg["search_mode"], "enable_rerank": cfg["rerank"],
        "enable_hyde": cfg["hyde"], "enable_crag": cfg["crag"], "enable_self_reflective": cfg["self_rag"],
    }
    row = {"id": g.id, "base_id": g.base_id, "language": g.language, "type": g.type,
           "adversarial_kind": g.adversarial_kind or "", "question": g.question}

    t0 = time.perf_counter()
    chunks = with_rate_limit_retry(retrieve, g.question, flags=flags)
    t1 = time.perf_counter()
    row["retrieval_latency_s"] = round(t1 - t0, 3)
    row["retrieved"] = json.dumps([[c.source, c.page_number, round(c.score, 4)] for c in chunks],
                                  ensure_ascii=False)

    if g.should_answer:
        gold = [Evidence(r.source, r.page) for r in g.relevant_documents]
        for k in RETRIEVAL_KS:
            row[f"recall@{k}"] = recall_at_k(chunks, gold, k)
        row["precision@5"] = precision_at_k(chunks, gold, 5)
        row["mrr"] = mrr(chunks, gold, k=cfg["top_k"])

    if cfg["generate"]:
        response = with_rate_limit_retry(_generate, g.question, chunks, flags=flags)
        t2 = time.perf_counter()
        answer = response.answer
        row.update({
            "generation_latency_s": round(t2 - t1, 3),
            "total_latency_s": round(t2 - t0, 3),
            "answer": answer,
            "refusal_type": refusal_type(answer) or "",
            "outcome": answer_outcome(g.should_answer, answer, g.adversarial_kind, g.correct_facts),
            "has_citation": int(bool(extract_citations(answer))),
            "citation_precision": citation_precision(answer, chunks),
            "answer_language": detect_language(answer),
        })
        row["language_match"] = int(row["answer_language"] == g.language)
        row["_contexts"] = [c.text for c in chunks]  # for Ragas, kept in the .contexts.json sidecar
    else:
        row["total_latency_s"] = row["retrieval_latency_s"]

    # HyDE / CRAG / Self-RAG swallow LLM errors; such a row would measure a broken pipeline
    if STATS["errors"] > errors_before:
        if _is_daily_limit(STATS["last_error"]):
            raise DailyLimitReached(STATS["last_error"][:300])
        raise RuntimeError(f"LLM error inside the pipeline: {STATS['last_error'][:250]}")
    row["llm_tokens"] = sum(STATS["tokens"].values()) - tokens_before
    return row


def sample_answerable(goldens: list, n: int) -> list:
    """Keep n answerable base_ids, evenly spaced (the file is ordered by document)."""
    bases = list(dict.fromkeys(g.base_id for g in goldens if g.type == "answerable"))
    if n <= 0 or n >= len(bases):
        return goldens
    keep = {bases[round(i * (len(bases) - 1) / (n - 1))] for i in range(n)} if n > 1 else {bases[0]}
    return [g for g in goldens if g.type != "answerable" or g.base_id in keep]


def ragas_subset(rows: list[dict], limit: int) -> list[dict]:
    """Answerable, answered questions, balanced over languages."""
    pool = {lang: [r for r in rows if r["language"] == lang and r.get("outcome") == "answered"]
            for lang in LANGS}
    picked, i = [], 0
    while len(picked) < limit and any(i < len(v) for v in pool.values()):
        for lang in LANGS:
            if i < len(pool[lang]) and len(picked) < limit:
                picked.append(pool[lang][i])
        i += 1
    return picked


def _mean(values) -> float | None:
    vals = [float(v) for v in values if v not in (None, "")]
    return round(statistics.fmean(vals), 4) if vals else None


# Outcomes of unanswerable / adversarial questions (denominator of hallucination rates)
_NOT_ANSWERABLE = {"hallucination", "correct_refusal", "premise_corrected"}


def _rate(rows: list[dict], outcome: str, of: set[str]) -> float | None:
    pool = [r for r in rows if r.get("outcome") in of]
    return round(sum(r["outcome"] == outcome for r in pool) / len(pool), 4) if pool else None


def summarize(rows: list[dict], cfg: dict, raw_path: Path, started: str) -> dict:
    from app.config import settings

    ans = [r for r in rows if r["type"] == "answerable"]
    unans = [r for r in rows if r["type"] != "answerable"]

    def block(sub: list[dict], prefix: str = "") -> dict:
        sub_ans = [r for r in sub if r["type"] == "answerable"]
        out = {f"{prefix}n": len(sub)}
        for k in RETRIEVAL_KS:
            out[f"{prefix}recall@{k}"] = _mean(r.get(f"recall@{k}") for r in sub_ans)
        out[f"{prefix}precision@5"] = _mean(r.get("precision@5") for r in sub_ans)
        out[f"{prefix}mrr"] = _mean(r.get("mrr") for r in sub_ans)
        if cfg["generate"]:
            out[f"{prefix}over_refusal_rate"] = _rate(sub, "over_refusal", {"answered", "over_refusal"})
            out[f"{prefix}hallucination_rate"] = _rate(sub, "hallucination", _NOT_ANSWERABLE)
            out[f"{prefix}language_match"] = _mean(r.get("language_match") for r in sub)
            for m in RAGAS_METRICS:
                out[f"{prefix}{m}"] = _mean(r.get(m) for r in sub)
        return out

    latencies = [float(r["total_latency_s"]) for r in rows if r.get("total_latency_s") not in (None, "")]
    summary = {
        "config": cfg["name"], "date": started, "raw_file": raw_path.relative_to(ROOT).as_posix(),
        "questions": len(rows), "answerable": len(ans), "unanswerable_or_adversarial": len(unans),
        "chunk_size": cfg["chunk_size"], "search_mode": cfg["search_mode"], "top_k": cfg["top_k"],
        "rerank": cfg["rerank"], "hyde": cfg["hyde"], "crag": cfg["crag"], "self_rag": cfg["self_rag"],
        "generate": cfg["generate"],
        "languages": ",".join(cfg.get("languages") or []) or "all",
        "llm_answer": settings.llm_model_answer if cfg["generate"] else "",
        "llm_grader": settings.llm_model_grader,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model if cfg["rerank"] else "",
        **block(rows),
        "retrieval_latency_mean_s": _mean(r.get("retrieval_latency_s") for r in rows),
        "generation_latency_mean_s": _mean(r.get("generation_latency_s") for r in rows),
        "llm_tokens_mean": _mean(r.get("llm_tokens") for r in rows) if cfg["generate"] else None,
        "total_latency_mean_s": _mean(latencies),
        "total_latency_p50_s": round(statistics.median(latencies), 3) if latencies else None,
        "errors": sum(1 for r in rows if r.get("error")),
    }
    if cfg["generate"]:
        summary["refusal_rate_unanswerable"] = _rate(
            [r for r in rows if r["type"] == "unanswerable"], "correct_refusal", _NOT_ANSWERABLE)
        summary["refusal_rate_adversarial"] = _rate(
            [r for r in rows if r["type"] == "adversarial"], "correct_refusal", _NOT_ANSWERABLE)
        summary["premise_corrected_rate"] = _rate(
            [r for r in rows if r.get("adversarial_kind") == "fake_premise"], "premise_corrected", _NOT_ANSWERABLE)
        summary["citation_rate"] = _mean(r.get("has_citation") for r in rows if r.get("outcome") == "answered")
    for lang in LANGS:
        summary.update(block([r for r in rows if r["language"] == lang], prefix=f"{lang}_"))
    return summary


def append_summary(summary: dict, path: Path) -> None:
    rows, fields = [], list(summary)
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fields = list(dict.fromkeys([*(reader.fieldnames or []), *summary]))
    rows.append(summary)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_raw(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_raw(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RAW_FIELDS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(description="Run one experiment config over the eval questions")
    ap.add_argument("--config", required=True)
    ap.add_argument("--questions", default=str(ROOT / "eval" / "coop_questions.yaml"))
    ap.add_argument("--no-ragas", action="store_true", help="skip Ragas even if the config enables it")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions (dry run)")
    ap.add_argument("--resume", default=None, help="continue this raw CSV (skips finished ids)")
    ap.add_argument("--summary", default=str(ROOT / "results" / "summary.csv"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    from app.config import settings
    from eval.schema import load_coop_goldens

    # One Qdrant collection per chunk size (coop_<size>); the query cache is not used here
    settings.chunk_size = int(cfg["chunk_size"])
    goldens = load_coop_goldens(args.questions)
    if cfg.get("question_types"):
        goldens = [g for g in goldens if g.type in cfg["question_types"]]
    if cfg.get("languages"):  # e.g. [en] for the expensive Exp 6 configs (Groq budget)
        goldens = [g for g in goldens if g.language in cfg["languages"]]
    if cfg.get("answerable_sample"):
        goldens = sample_answerable(goldens, int(cfg["answerable_sample"]))
    if not cfg["generate"]:
        goldens = [g for g in goldens if g.should_answer]  # only retrieval metrics make sense
    if args.limit:
        goldens = goldens[: args.limit]

    started = datetime.now().isoformat(timespec="seconds")
    raw_dir = ROOT / "results" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = Path(args.resume) if args.resume else raw_dir / f"{cfg['name']}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    rows = read_raw(raw_path) if raw_path.exists() else []
    done = {r["id"] for r in rows if not r.get("error")}
    rows = [r for r in rows if r["id"] in done]
    ctx_path = raw_path.with_suffix(".contexts.json")  # retrieved texts, for Ragas after a resume
    contexts = json.loads(ctx_path.read_text(encoding="utf-8")) if ctx_path.exists() else {}
    print(f"{cfg['name']}: {len(goldens)} questions -> {raw_path.relative_to(ROOT)} "
          f"({len(done)} already done) | collection coop_{settings.chunk_size}")

    # Warm-up: load bge-m3 / the reranker / the sparse index before timing, so the first
    # question's latency does not include model loading
    if any(g.id not in done for g in goldens):
        from app.services.rag_service import retrieve

        retrieve("PM-KISAN warm-up", flags={"search_mode": cfg["search_mode"], "enable_rerank": cfg["rerank"],
                                            "top_k": cfg["top_k"], "enable_crag": False})

    resume_cmd = (f"uv run --env-file .env python eval/run_experiment.py --config {args.config} "
                  f"--questions {args.questions} --resume {raw_path.relative_to(ROOT).as_posix()}")
    for i, g in enumerate(goldens, start=1):
        if g.id in done:
            continue
        try:
            row = run_question(g, cfg)
        except DailyLimitReached as exc:
            print(f"\nGroq daily limit reached at {g.id}: {exc}\n{len(rows)}/{len(goldens)} questions saved. "
                  f"No summary row yet. Resume later with:\n  {resume_cmd}")
            return 3
        except Exception as exc:  # noqa: BLE001
            row = {"id": g.id, "base_id": g.base_id, "language": g.language, "type": g.type,
                   "question": g.question, "error": f"{type(exc).__name__}: {exc}"[:300]}
        if "_contexts" in row:
            contexts[g.id] = row.pop("_contexts")
            ctx_path.write_text(json.dumps(contexts, ensure_ascii=False), encoding="utf-8")
        rows.append(row)
        write_raw(rows, raw_path)  # rewrite after every question: crash-safe
        status = row.get("error") or row.get("outcome") or f"recall@5={row.get('recall@5')}"
        print(f"  [{i}/{len(goldens)}] {g.id} {row.get('total_latency_s', '-')}s {status}")

    if cfg["ragas"] and cfg["generate"] and not args.no_ragas:
        from eval.ragas_adapter import run as run_ragas

        # Same balanced subset on every (resumed) run; only rows without scores are sent
        subset = [r for r in ragas_subset([r for r in rows if r["id"] in contexts], int(cfg["ragas_limit"]))
                  if r.get("faithfulness") in (None, "")]
        by_id = {g.id: g for g in goldens}
        print(f"Ragas on {len(subset)} answered questions ...")
        if subset:
            scores = run_ragas([{"question": r["question"], "answer": r["answer"], "contexts": contexts[r["id"]],
                                 "ground_truth": by_id[r["id"]].expected_answer} for r in subset])
            for r, s in zip(subset, scores, strict=True):
                for m in RAGAS_METRICS:
                    v = s.get(m)
                    r[m] = None if v is None or v != v else round(float(v), 4)  # NaN -> empty
            write_raw(rows, raw_path)

    rows = read_raw(raw_path)  # CSV values, same as a resumed run would see
    failed = sum(bool(r.get("error")) for r in rows)
    if failed:
        print(f"{failed} question(s) failed; rerun them with:\n  {resume_cmd}")
    summary = summarize(rows, cfg, raw_path, started)
    append_summary(summary, Path(args.summary))
    lang_prefixes = tuple(f"{lang}_" for lang in LANGS)  # "mrr" starts with "mr" too
    print(json.dumps({k: v for k, v in summary.items() if not k.startswith(lang_prefixes)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
