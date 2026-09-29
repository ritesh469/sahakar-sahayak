"""P15: paper figures, read ONLY from results/*.csv -> results/figures/*.png.

    uv run python scripts/make_plots.py

Every figure has axis labels with units and the question count (n=...). A figure (or panel)
whose CSV is not there yet is skipped with a message: rerun after new experiments
(eval/make_result_tables.py writes the CSVs).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"

# Reference palette of the dataviz method (light mode). Categorical slots 1-4 pass the CVD and
# normal-vision checks as adjacent pairs; slots 3-4 are below 3:1 contrast on the surface, so
# bars carry value labels (and the paper has the same numbers as tables).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
ORDINAL_BLUE = ["#86b6ef", "#2a78d6", "#104281"]  # light -> dark, for ordered series (k, off -> on)
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
LANG_LABEL = {"all": "All", "en": "English", "hi": "Hindi", "mr": "Marathi", "hinglish": "Hinglish"}
LANGS = ["en", "hi", "mr", "hinglish"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True, "legend.frameon": False,
    "legend.fontsize": 9, "text.color": INK,
})


# ---------- data ----------

def read(name: str) -> list[dict] | None:
    path = RESULTS / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(value) -> float | None:
    return None if value in (None, "") else float(value)


def has(rows: list[dict] | None, col: str) -> bool:
    return bool(rows) and any(num(r.get(col)) is not None for r in rows)


# ---------- drawing ----------

def grouped_bars(ax, groups: list[str], series: list[tuple[str, list, str]], labels=True,
                 fmt="{:.2f}", ylim: tuple[float, float] | None = (0, 1.05)) -> None:
    """series = [(name, values per group, color)]; None values are left out."""
    k = len(series)
    slot = 0.8 / k
    width = min(slot * 0.88, 0.3)  # leaves a gap between neighbouring bars
    for i, (name, values, color) in enumerate(series):
        xs = [g + (i - (k - 1) / 2) * slot for g in range(len(groups))]
        pts = [(x, v) for x, v in zip(xs, values) if v is not None]
        bars = ax.bar([p[0] for p in pts], [p[1] for p in pts], width=width, color=color, label=name)
        if labels is True or (isinstance(labels, set) and name in labels):
            ax.bar_label(bars, labels=[fmt.format(p[1]) for p in pts], padding=2, fontsize=7.5,
                         color=INK2)
    ax.set_xticks(range(len(groups)), groups)
    ax.tick_params(axis="x", length=0)
    if ylim:
        ax.set_ylim(*ylim)
    if k > 1:
        ax.legend(loc="upper left", ncols=min(k, 4), bbox_to_anchor=(0, 1.0))


def save(fig, name: str, source: str) -> None:
    fig.tight_layout()
    # below everything (bbox_inches="tight" grows the image to include it)
    fig.text(0.01, 0, f"Source: {source}", fontsize=7.5, color=MUTED, ha="left", va="top")
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote results/figures/{name}")


def skip(name: str, why: str) -> None:
    print(f"skip {name}: {why}")


def n_of(rows: list[dict], col: str = "questions") -> str:
    values = sorted({r.get(col, "") for r in rows if r.get(col)})
    return "/".join(values) if values else "?"


# ---------- figures ----------

def recall_at_k(ret) -> None:
    if not ret:
        return skip("recall_at_k.png", "results/retrieval_results.csv missing")
    fig, ax = plt.subplots(figsize=(10, 4.6))
    series = [(f"k = {k}", [num(r[f"recall@{k}"]) for r in ret], ORDINAL_BLUE[i])
              for i, k in enumerate((1, 3, 5))]
    grouped_bars(ax, [r["method"] for r in ret], series, labels={"k = 5"}, ylim=(0, 1.12))
    ax.set_ylabel("Recall@k (share of questions, 0–1)")
    ax.set_xlabel("Retrieval method (chunk size 512 tokens)")
    ax.set_title(f"Recall@k by retrieval method (n = {n_of(ret)} answerable questions, 4 languages)")
    save(fig, "recall_at_k.png", "results/retrieval_results.csv")


def mrr(ret) -> None:
    if not ret:
        return skip("mrr.png", "results/retrieval_results.csv missing")
    fig, ax = plt.subplots(figsize=(9, 4.2))
    grouped_bars(ax, [r["method"] for r in ret], [("MRR", [num(r["mrr"]) for r in ret], SERIES[0])])
    ax.set_ylabel("Mean reciprocal rank (0–1)")
    ax.set_xlabel("Retrieval method (chunk size 512 tokens)")
    ax.set_title(f"MRR by retrieval method (n = {n_of(ret)} answerable questions)")
    save(fig, "mrr.png", "results/retrieval_results.csv")


def chunk_size(chunk) -> None:
    if not chunk:
        return skip("chunk_size.png", "results/chunking_results.csv missing")
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    groups = [f"{r['chunk_size']} tokens\n({int(num(r['chunks'])):,} chunks)" if r.get("chunks")
              else f"{r['chunk_size']} tokens" for r in chunk]
    grouped_bars(ax, groups, [("Recall@5", [num(r["recall@5"]) for r in chunk], SERIES[0]),
                              ("MRR", [num(r["mrr"]) for r in chunk], SERIES[1])], ylim=(0, 1.12))
    ax.set_ylabel("Score (0–1)")
    ax.set_xlabel("Maximum chunk size (bge-m3 tokens)")
    ax.set_title(f"Effect of chunk size, {chunk[0]['method']} (n = {n_of(chunk)} questions)")
    save(fig, "chunk_size.png", "results/chunking_results.csv")


def rerank_effect(rer) -> None:
    if not rer:
        return skip("rerank_effect.png", "results/reranking_results.csv missing")
    pairs = list(dict.fromkeys(r["pair"] for r in rer))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for ax, metric, label in zip(axes, ("recall@5", "mrr"), ("Recall@5", "MRR")):
        values = {(r["pair"], r["rerank"]): num(r[metric]) for r in rer}
        grouped_bars(ax, [p.replace(" (", "\n(") for p in pairs],
                     [("rerank off", [values.get((p, "False")) for p in pairs], ORDINAL_BLUE[0]),
                      ("rerank on", [values.get((p, "True")) for p in pairs], ORDINAL_BLUE[2])],
                     ylim=(0, 1.12))
        ax.set_title(label)
        ax.set_xlabel("Search method (chunk size 512)")
    axes[0].set_ylabel("Score (0–1)")
    fig.suptitle(f"Effect of the bge-reranker-v2-m3 reranker (n = {n_of(rer)} questions per run)",
                 x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, "rerank_effect.png", "results/reranking_results.csv")


def faithfulness(rer) -> None:
    rows = [r for r in (rer or []) if num(r.get("faithfulness")) is not None]
    if not rows:
        return skip("faithfulness.png", "no Ragas scores yet (Exp 3 runs with answers)")
    metrics = [("faithfulness", "Faithfulness"), ("answer_relevancy", "Answer relevancy"),
               ("context_precision", "Context precision"), ("context_recall", "Context recall")]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    series = [(f"rerank {'on' if r['rerank'] == 'True' else 'off'} ({r['config']}, n={r['questions']})",
               [num(r.get(m)) for m, _ in metrics], ORDINAL_BLUE[2 if r["rerank"] == "True" else 0])
              for r in rows]
    grouped_bars(ax, [label for _, label in metrics], series, ylim=(0, 1.12))
    ax.set_ylabel("Ragas score (0–1)")
    ax.set_xlabel("Ragas metric (LLM judge: " + (rows[0].get("llm_grader") or "?") + ")")
    ax.set_title("Answer quality with and without reranking (Ragas, language-balanced subset)")
    save(fig, "faithfulness.png", "results/reranking_results.csv")


def hallucination_rate(hal, adv) -> None:
    if not hal and not adv:
        return skip("hallucination_rate.png", "Exp 5 / Exp 6 runs with answers not done yet")
    panels = int(bool(hal)) + int(bool(adv))
    fig, axes = plt.subplots(panels, 1, figsize=(10, 4.6 * panels), squeeze=False)
    axes = [row[0] for row in axes]
    if hal:
        ax = axes.pop(0)
        by = {(r["type"], r["adversarial_kind"], r["language"]): r for r in hal}
        langs = ["all", *LANGS]

        def col(qtype, metric):
            return [num(by.get((qtype, "all", lang), {}).get(metric)) for lang in langs]

        n = {t: by.get((t, "all", "all"), {}).get("n", "?") for t in ("answerable", "unanswerable", "adversarial")}
        grouped_bars(ax, [LANG_LABEL[lang] for lang in langs], [
            (f"Hallucination, unanswerable (n={n['unanswerable']})", col("unanswerable", "hallucination_rate"), SERIES[0]),
            (f"Hallucination, adversarial (n={n['adversarial']})", col("adversarial", "hallucination_rate"), SERIES[1]),
            (f"Over-refusal, answerable (n={n['answerable']})", col("answerable", "over_refusal_rate"), SERIES[2]),
        ], ylim=(0, 1.2))
        ax.set_ylabel("Rate (share of questions, 0–1)")
        ax.set_xlabel("Question language")
        ax.set_title(f"Exp 5: hallucination and over-refusal ({hal[0]['config']})")
    if adv:
        ax = axes.pop(0)
        grouped_bars(ax, [r["feature"].replace(", ", ",\n").replace(" (", "\n(") for r in adv], [
            ("Hallucination (unanswerable + adversarial)", [num(r["hallucination_rate"]) for r in adv], SERIES[0]),
            ("Over-refusal (answerable)", [num(r["over_refusal_rate"]) for r in adv], SERIES[2]),
        ], ylim=(0, 1.2))
        ax.set_ylabel("Rate (share of questions, 0–1)")
        ax.set_xlabel("Advanced RAG feature (English questions)")
        ax.set_title(f"Exp 6: advanced RAG (n = {n_of(adv, 'n')} questions per run)")
    fig.tight_layout()
    save(fig, "hallucination_rate.png",
         ", ".join(f for f, ok in (("results/hallucination_results.csv", hal),
                                   ("results/advanced_rag_results.csv", adv)) if ok))


def latency(ret, rer, adv) -> None:
    if not ret:
        return skip("latency.png", "results/retrieval_results.csv missing")
    answer_rows = [(f"{r['method']}\n({r['config']})", r) for r in (rer or [])
                   if num(r.get("generation_latency_mean_s")) is not None]
    answer_rows += [(r["feature"].replace(", ", ",\n"), r) for r in (adv or [])
                    if num(r.get("generation_latency_mean_s")) is not None and r["config"].startswith("exp6")]
    panels = 2 if answer_rows else 1
    fig, axes = plt.subplots(1, panels, figsize=(8 * panels, 4.4), squeeze=False)
    ax = axes[0][0]
    grouped_bars(ax, [r["method"].replace(" + ", "\n+ ") for r in ret],
                 [("retrieval", [1000 * num(r["retrieval_latency_mean_s"]) for r in ret], SERIES[0])],
                 fmt="{:.0f}", ylim=None)
    ax.set_ylabel("Mean retrieval latency (ms per question)")
    ax.set_xlabel("Retrieval method (GPU: RTX 4060)")
    ax.set_title(f"Retrieval latency (n = {n_of(ret)} questions)")
    ax.margins(y=0.15)
    if answer_rows:
        ax = axes[0][1]
        names = [name for name, _ in answer_rows]
        gen = [num(r["generation_latency_mean_s"]) for _, r in answer_rows]
        total = [num(r.get("total_latency_mean_s")) for _, r in answer_rows]
        other = [max((t or 0) - g, 0) for t, g in zip(total, gen)]
        ax.bar(names, other, width=0.5, color=SERIES[0], label="retrieval + other")
        bars = ax.bar(names, gen, width=0.5, bottom=other, color=SERIES[1], label="LLM generation")
        ax.bar_label(bars, labels=[f"{t:.1f} s" for t in total], padding=2, fontsize=7.5, color=INK2)
        ax.set_ylabel("Mean latency (s per question)")
        ax.set_xlabel("Configuration")
        ax.set_title("End-to-end latency with answer generation")
        ax.legend(loc="upper left")
        ax.margins(y=0.15)
    fig.tight_layout()
    save(fig, "latency.png", "results/retrieval_results.csv"
         + (", results/reranking_results.csv, results/advanced_rag_results.csv" if answer_rows else ""))


def language_wise(ret, ml) -> None:
    if not ret:
        return skip("language_wise.png", "results/retrieval_results.csv missing")
    panels = 2 if ml else 1
    fig, axes = plt.subplots(panels, 1, figsize=(11, 4.6 * panels), squeeze=False)
    ax = axes[0][0]
    grouped_bars(ax, [r["method"] for r in ret],
                 [(LANG_LABEL[lang], [num(r[f"{lang}_recall@5"]) for r in ret], SERIES[i])
                  for i, lang in enumerate(LANGS)], ylim=(0, 1.15))
    ax.set_ylabel("Recall@5 (0–1)")
    ax.set_xlabel("Retrieval method (chunk size 512)")
    per_lang = "/".join(sorted({ret[0].get(f"{lang}_n", "?") for lang in LANGS}))
    ax.set_title(f"Recall@5 by question language (n = {per_lang} answerable questions per language)")
    if ml:
        ax = axes[1][0]
        rows = [r for r in ml if r["language"] in LANGS]
        metrics = [(m, label) for m, label in (("recall@5", "Recall@5"), ("language_match", "Answer in question's language"),
                                               ("over_refusal_rate", "Over-refusal"),
                                               ("hallucination_rate", "Hallucination"),
                                               ("faithfulness", "Faithfulness (Ragas)")) if has(rows, m)]
        grouped_bars(ax, [label for _, label in metrics],
                     [(f"{LANG_LABEL[r['language']]} (n={r['n']})", [num(r.get(m)) for m, _ in metrics], SERIES[i])
                      for i, r in enumerate(rows)], ylim=(0, 1.15))
        ax.set_ylabel("Score or rate (0–1)")
        ax.set_xlabel(f"Metric ({ml[0]['config']}, answers by {ml[0].get('llm_answer') or '?'})")
        ax.set_title("Exp 4: answer quality by question language")
    fig.tight_layout()
    save(fig, "language_wise.png", "results/retrieval_results.csv"
         + (", results/multilingual_results.csv" if ml else ""))


def script_match(sm) -> None:
    if not sm:
        return skip("script_match.png", "results/script_match_results.csv missing")
    rows = [r for r in sm if r["answer_doc_in_question_script"] == "True"]
    methods = ["tfidf", "bm25", "dense"]
    by = {(r["method"], r["language"]): r for r in rows}
    groups = [f"{LANG_LABEL[lang]}\n(n={by.get(('bm25', lang), {}).get('n', '?')})" for lang in LANGS]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    grouped_bars(ax, groups, [(m if m != "tfidf" else "tfidf (old tokenizer)",
                               [num(by.get((m, lang), {}).get("recall@5")) for lang in LANGS], SERIES[i])
                              for i, m in enumerate(methods)], ylim=(0, 1.15))
    ax.set_ylabel("Recall@5 (0–1)")
    ax.set_xlabel("Question language (only questions whose answer document is in the same script)")
    ax.set_title("Lexical search vs dense when the document shares the question's script")
    save(fig, "script_match.png", "results/script_match_results.csv")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ret, chunk = read("retrieval_results.csv"), read("chunking_results.csv")
    rer, ml = read("reranking_results.csv"), read("multilingual_results.csv")
    hal, adv = read("hallucination_results.csv"), read("advanced_rag_results.csv")
    recall_at_k(ret)
    mrr(ret)
    chunk_size(chunk)
    rerank_effect(rer)
    faithfulness(rer)
    hallucination_rate(hal, adv)
    latency(ret, rer, adv)
    language_wise(ret, ml)
    script_match(read("script_match_results.csv"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
