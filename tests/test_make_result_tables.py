"""P13: result tables are computed from raw rows, never typed in."""

import csv

import yaml

from eval import make_result_tables as mrt


def _row(qid, qtype, outcome, lang="en", error="", **extra):
    return {"id": qid, "type": qtype, "outcome": outcome, "language": lang, "error": error,
            "recall@5": "1.0", "mrr": "1.0", "language_match": "1", "has_citation": "1",
            "generation_latency_s": "2.0", "total_latency_s": "3.0", "llm_tokens": "100",
            "adversarial_kind": "", **extra}


def test_answer_metrics_rates_and_errors():
    rows = [
        _row("a1", "answerable", "answered"),
        _row("a2", "answerable", "over_refusal", mrr="0.0", **{"recall@5": "0.0"}),
        _row("u1", "unanswerable", "correct_refusal"),
        _row("u2", "unanswerable", "hallucination"),
        _row("x1", "adversarial", "premise_corrected"),
        _row("x2", "adversarial", "", error="timeout"),
    ]
    m = mrt.answer_metrics(rows)
    assert m["n"] == 5 and m["errors"] == 1
    assert m["answered_rate"] == 0.5 and m["over_refusal_rate"] == 0.5
    assert m["refusal_rate_unanswerable"] == 0.5
    assert m["hallucination_rate"] == round(1 / 3, 4)  # u2 out of u1, u2, x1
    assert m["recall@5"] == 0.5


def test_script_match(tmp_path):
    sources = tmp_path / "sources.csv"
    with sources.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "title", "source_url", "download_date", "language", "category"])
        w.writerows([["a_en.pdf", "", "", "", "en", ""], ["b_hi.pdf", "", "", "", "hi", ""],
                     ["c.pdf", "", "", "", "en+hi", ""]])
    questions = tmp_path / "q.yaml"
    questions.write_text(yaml.safe_dump([
        {"id": "ans-001-hi", "language": "hi", "relevant_documents": [{"source": "a_en.pdf"}]},
        {"id": "ans-002-mr", "language": "mr", "relevant_documents": [{"source": "b_hi.pdf"}]},
        {"id": "ans-003-hinglish", "language": "hinglish", "relevant_documents": [{"source": "c.pdf"}]},
    ]), encoding="utf-8")
    match = mrt.load_script_match(questions, sources)
    assert match == {"ans-001-hi": False, "ans-002-mr": True, "ans-003-hinglish": True}


def test_significance_sign_test(monkeypatch):
    a = [{"id": f"q{i}", "type": "answerable", "language": "en", "error": "",
          "recall@5": "0.0", "mrr": "0.0"} for i in range(8)]
    b = [{**r, "recall@5": "1.0", "mrr": "1.0"} for r in a]
    raws = {"A": a, "B": b}
    monkeypatch.setattr(mrt, "SIGNIFICANCE_PAIRS", [("A vs B", "A", "B")])
    monkeypatch.setattr(mrt, "load_raw", lambda row: raws[row["config"]])
    summ = {"A": {"config": "A", "date": "d1"}, "B": {"config": "B", "date": "d2"}}
    rows = [r for r in mrt.significance(summ) if r["language"] == "all" and r["metric"] == "recall@5"]
    assert rows[0]["b_better"] == 8 and rows[0]["a_better"] == 0
    assert rows[0]["sign_test_p"] == round(2 * 0.5 ** 8, 4)
