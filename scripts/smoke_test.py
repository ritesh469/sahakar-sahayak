"""Day-1 smoke test (P7): 10 questions through rag_service, one per row.

Prints the answer, the retrieved sources with page numbers and the latency (retrieval and
generation separately), and checks whether an expected document is in the top-k and the
answer is in the question's language (OK needs both, or the right refusal). Expected
sources were read from the chunk texts by hand; parallel language versions of the same
document count as a hit (e.g. ncp_2025_en.pdf for a Hindi question about ncp_2025_hi.pdf).

Usage:
    uv run --env-file .env python scripts/smoke_test.py [--search-mode dense] [--no-rerank]
        [--top-k 5] [--out results/smoke_test.json]
"""

from __future__ import annotations

import app  # noqa: F401  (first: Windows DLL load order, CLAUDE.md S9)

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (id, language, type, question, expected sources: {filename: page the fact is on, None =
# page not checked because the text layer is too damaged to locate it})
QUESTIONS: list[tuple[str, str, str, str, dict[str, int | None]]] = [
    ("en1", "en", "answerable",
     "By how much was the surcharge on cooperative societies reduced for income between "
     "1 crore and 10 crore rupees?",
     {"coop_income_tax_benefits.pdf": 1}),
    ("en2", "en", "answerable",
     "What minimum pension does a subscriber get under PM Kisan Maan-Dhan Yojana, and from what age?",
     {"pmkmy_faqs_en.pdf": 1, "pmkmy_guidelines_en.pdf": 16}),
    ("hi1", "hi", "answerable",
     "राष्ट्रीय सहकारिता नीति 2025 के अनुसार कितने करोड़ लोगों को सहकारी समितियों के दायरे में "
     "लाने का लक्ष्य है?",
     {"ncp_2025_hi.pdf": 25, "ncp_2025_en.pdf": 23}),
    ("hi2", "hi", "answerable",
     "अन्न भंडारण योजना के तहत पैक्स स्तर पर कौन-कौन सी कृषि अवसंरचना बनाई जाती है?",
     {"grain_storage_plan_sop_hi.pdf": None, "grain_storage_plan_sop_en.pdf": 7}),
    ("mr1", "mr", "answerable",
     "पुण्यश्लोक अहिल्यादेवी होळकर शेतकरी कर्जमुक्ती योजनेत किती रकमेपर्यंत कर्जमुक्ती दिली जाते?",
     {"mh_farmer_loan_waiver_2026_mr.pdf": 1}),
    ("mr2", "mr", "answerable",
     "महिला शेतकरी सक्षमीकरण अधिनियमानुसार राज्य संनियंत्रण समितीचे अध्यक्ष कोण असतात?",
     {"mh_women_farmer_act_2026_mr.pdf": 8, "mh_women_farmer_act_2026_en.pdf": 7}),
    ("hinglish1", "hinglish", "answerable",
     "Cooperative sugar mills wali NCDC scheme ka total outlay kitna hai aur kin saalon mein milega?",
     {"ncdc_sugar_mills_scheme.pdf": 1}),
    ("hinglish2", "hinglish", "answerable",
     "PM-KISAN ka e-KYC kaunse tareekon se kar sakte hain?",
     {"pmkisan_ekyc_note_en.pdf": 1, "pmkisan_ekyc_note_hi.pdf": 1, "pmkisan_ekyc_note_mr.pdf": 1}),
    ("unans1", "en", "unanswerable",
     "How many cooperative societies were registered in Bihar in 2024?", {}),
    ("ood1", "hinglish", "out_of_domain",
     "Paneer butter masala kaise banate hain?", {}),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--search-mode", default="dense")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--out", default="results/smoke_test.json")
    args = ap.parse_args()

    from app.config import settings
    from app.services.language import detect_language
    from app.services.rag_service import _generate, retrieve
    from eval.metrics import refusal_type

    flags = {"search_mode": args.search_mode, "enable_rerank": not args.no_rerank,
             "top_k": args.top_k, "enable_crag": False, "enable_hyde": False,
             "enable_self_reflective": False}
    print(f"LLM {settings.llm_model_answer} ({settings.llm_provider}) | embeddings "
          f"{settings.embedding_model} | collection {settings.qdrant_collection_prefix}_"
          f"{settings.chunk_size} | flags {flags}\n")

    rows = []
    for qid, lang, qtype, question, expected in QUESTIONS:
        t0 = time.perf_counter()
        chunks = retrieve(question, flags=flags)
        t1 = time.perf_counter()
        answer = _generate(question, chunks, flags=flags).answer
        t2 = time.perf_counter()

        sources = [(c.source, c.page_number) for c in chunks]
        hit_rank = next((i for i, (s, _) in enumerate(sources, 1) if s in expected), None)
        page_hit = any(s in expected and p is not None and expected[s] is not None
                       and 0 <= expected[s] - p <= 1
                       for s, p in sources)
        refusal = refusal_type(answer) or ""
        answer_lang = detect_language(answer)
        if qtype == "answerable":
            ok = hit_rank is not None and not refusal
        elif qtype == "unanswerable":
            ok = refusal == "no_info"
        else:
            ok = refusal == "out_of_domain"
        ok = ok and answer_lang == lang  # the answer must be in the question's language
        row = {
            "id": qid, "language": lang, "type": qtype, "question": question,
            "expected": expected, "sources": sources, "expected_rank": hit_rank,
            "expected_page_in_top_k": page_hit, "answer": answer, "refusal": refusal,
            "answer_language": answer_lang, "ok": ok,
            "retrieval_s": round(t1 - t0, 2), "generation_s": round(t2 - t1, 2),
            "total_s": round(t2 - t0, 2),
        }
        rows.append(row)

        print("=" * 100)
        print(f"[{qid}] ({lang}, {qtype}) {question}")
        print(f"Answer ({row['answer_language']}): {answer}")
        print("Sources:")
        for i, (s, p) in enumerate(sources, 1):
            mark = "  <- expected" if s in expected else ""
            print(f"  {i}. {s}, p. {p}{mark}")
        if expected:
            where = f"rank {hit_rank}" if hit_rank else "NOT in top-k"
            print(f"Expected document: {where}; expected page in top-k: {page_hit}")
        print(f"Latency: retrieval {row['retrieval_s']} s + generation {row['generation_s']} s "
              f"= {row['total_s']} s | {'OK' if ok else 'CHECK'}")

    print("\n" + "=" * 100)
    print(f"{'id':<11}{'lang':<10}{'answer':<10}{'type':<15}{'doc rank':<10}{'refusal':<15}"
          f"{'total s':<9}ok")
    for r in rows:
        rank = r["expected_rank"] if r["expected"] else "-"
        print(f"{r['id']:<11}{r['language']:<10}{r['answer_language']:<10}{r['type']:<15}"
              f"{str(rank or 'miss'):<10}"
              f"{r['refusal'] or '-':<15}{r['total_s']:<9}{'OK' if r['ok'] else 'CHECK'}")
    misses = [r["id"] for r in rows if r["expected"] and not r["expected_rank"]]
    print(f"\n{sum(r['ok'] for r in rows)}/{len(rows)} OK; expected document missing from "
          f"top-{args.top_k}: {', '.join(misses) or 'none'}")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "date": datetime.now().isoformat(timespec="seconds"), "flags": flags,
        "llm_answer": settings.llm_model_answer, "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model if flags["enable_rerank"] else "",
        "collection": f"{settings.qdrant_collection_prefix}_{settings.chunk_size}",
        "questions": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
