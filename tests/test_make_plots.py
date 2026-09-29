"""P15: every figure renders from the result CSVs, including the panels whose runs are still pending."""

import csv

from scripts import make_plots as mp

LANGS = ["en", "hi", "mr", "hinglish"]


def _write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _fake_results(d):
    ret = [{"config": c, "method": m, "questions": 232, "recall@1": 0.5, "recall@3": 0.7, "recall@5": 0.8,
            "mrr": 0.6, "retrieval_latency_mean_s": 0.3,
            **{f"{lang}_n": 58 for lang in LANGS}, **{f"{lang}_recall@5": 0.7 for lang in LANGS}}
           for c, m in (("exp2_bm25", "bm25"), ("exp2_dense", "dense"), ("exp1_chunk_512", "hybrid + rerank"))]
    _write(d / "retrieval_results.csv", ret)
    _write(d / "chunking_results.csv", [{"config": f"exp1_chunk_{s}", "chunk_size": s, "chunks": 1000,
                                         "method": "hybrid + rerank", "questions": 232, "recall@5": 0.8,
                                         "mrr": 0.7} for s in (256, 512, 1024)])
    _write(d / "reranking_results.csv", [
        {"config": c, "pair": "hybrid (answers + Ragas)", "method": m, "rerank": rr, "questions": 304,
         "recall@5": 0.8, "mrr": 0.7, "faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 0.7,
         "context_recall": 0.6, "llm_grader": "judge", "generation_latency_mean_s": 3.0,
         "total_latency_mean_s": 3.6}
        for c, m, rr in (("exp3_hybrid", "hybrid", "False"), ("exp3_hybrid_rerank", "hybrid + rerank", "True"))])
    _write(d / "multilingual_results.csv", [
        {"config": "exp3_hybrid_rerank", "language": lang, "n": 76, "llm_answer": "m", "recall@5": 0.8,
         "language_match": 0.95, "over_refusal_rate": 0.1, "hallucination_rate": 0.2, "faithfulness": 0.9}
        for lang in ["all", *LANGS]])
    _write(d / "hallucination_results.csv", [
        {"config": "exp3_hybrid_rerank", "type": t, "adversarial_kind": "all", "language": lang, "n": 10,
         "hallucination_rate": 0.2, "over_refusal_rate": 0.1}
        for t in ("answerable", "unanswerable", "adversarial") for lang in ["all", *LANGS]])
    _write(d / "advanced_rag_results.csv", [
        {"config": c, "feature": f, "n": 76, "hallucination_rate": 0.2, "over_refusal_rate": 0.1,
         "generation_latency_mean_s": 4.0, "total_latency_mean_s": 5.0}
        for c, f in (("exp3_hybrid_rerank", "baseline (hybrid + rerank)"), ("exp6_hyde", "HyDE"),
                     ("exp6_selfrag", "Self-RAG, refusal-aware prompt"))])
    _write(d / "script_match_results.csv", [
        {"method": m, "language": lang, "answer_doc_in_question_script": "True", "n": 40, "recall@5": 0.5}
        for m in ("tfidf", "bm25", "dense") for lang in LANGS])


def test_all_figures_render(tmp_path, monkeypatch):
    _fake_results(tmp_path)
    monkeypatch.setattr(mp, "RESULTS", tmp_path)
    monkeypatch.setattr(mp, "FIGURES", tmp_path / "figures")
    assert mp.main() == 0
    made = {p.name for p in (tmp_path / "figures").glob("*.png")}
    assert made == {"recall_at_k.png", "mrr.png", "chunk_size.png", "rerank_effect.png", "faithfulness.png",
                    "hallucination_rate.png", "latency.png", "language_wise.png", "script_match.png"}


def test_missing_results_are_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mp, "RESULTS", tmp_path)
    monkeypatch.setattr(mp, "FIGURES", tmp_path / "figures")
    assert mp.main() == 0
    assert "skip recall_at_k.png" in capsys.readouterr().out
    assert not (tmp_path / "figures").exists()
