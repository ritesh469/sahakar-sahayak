"""Validate eval/coop_questions.yaml against the documents (P10).

Checks, for every question:
  - schema (eval/schema.py CoopGolden) and consistent translations (same base_id);
  - every relevant_document exists in seed/docs/true_data and the page exists;
  - for answerable questions: the supporting_text really is on the given page (or the next one,
    for text that runs over a page break) in the text docling extracted.

Usage:
  uv run --env-file .env python scripts/validate_questions.py [--questions eval/coop_questions.yaml]
Exit code 1 if any error.
"""

import argparse
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "seed" / "docs" / "true_data"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\u200c", "").replace("\u200d", "")
    return " ".join(text.casefold().split())


def page_texts(doc) -> dict[int, str]:
    """page number -> text of the items on that page (0 = whole doc for page-less formats)."""
    pages: dict[int, list[str]] = {}
    for item, _ in doc.iterate_items():
        text = getattr(item, "text", "") or ""
        if not text and hasattr(item, "export_to_markdown"):  # tables carry no .text
            text = item.export_to_markdown(doc=doc)
        provs = getattr(item, "prov", None) or []
        for page in {p.page_no for p in provs} or {0}:
            pages.setdefault(page, []).append(text)
    from app.services.text_cleaning import clean_extracted_text

    return {p: clean_extracted_text(" ".join(t)) for p, t in pages.items()}


def find_quote(quote: str, texts: dict[int, str], page: int | None) -> str:
    """'exact' / 'approx' / '' (not found) for the quote on page..page+1 (or anywhere)."""
    from app.services.text_tokenizer import tokenize

    if page is None:
        haystack = " ".join(texts.values())
    else:
        haystack = " ".join(texts.get(p, "") for p in (page, page + 1))
    if norm(quote) in norm(haystack):
        return "exact"
    words = tokenize(quote, remove_stopwords=False)
    have = set(tokenize(haystack, remove_stopwords=False))
    if words and sum(w in have for w in words) / len(words) >= 0.9:
        return "approx"  # e.g. line breaks / hyphenation changed a few characters
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(description="Validate the evaluation questions")
    ap.add_argument("--questions", default=str(ROOT / "eval" / "coop_questions.yaml"))
    args = ap.parse_args()

    from app.services.document_processor import DocumentProcessor
    from eval.schema import load_coop_goldens

    try:
        goldens = load_coop_goldens(args.questions)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR schema: {exc}")
        return 1

    processor = DocumentProcessor()
    cache: dict[str, tuple[int, dict[int, str]]] = {}
    errors, warnings = [], []
    checked_quotes: dict[tuple, str] = {}
    reported_bases: set[str] = set()

    for g in goldens:
        matches = []
        for ref in g.relevant_documents:
            path = DOCS / ref.source
            if not path.exists():
                errors.append(f"{g.id}: {ref.source} not in seed/docs/true_data")
                continue
            if ref.source not in cache:
                doc, _ = processor.convert(path)
                cache[ref.source] = (doc.num_pages(), page_texts(doc))
            n_pages, texts = cache[ref.source]
            if ref.page is not None and not 1 <= ref.page <= n_pages:
                errors.append(f"{g.id}: {ref.source} has {n_pages} pages, not p. {ref.page}")
                continue
            if g.type == "answerable":
                # Translations share the original-language quote, so each quote is checked once
                key = (ref.source, ref.page, g.supporting_text)
                if key not in checked_quotes:
                    checked_quotes[key] = find_quote(g.supporting_text, texts, ref.page)
                matches.append(checked_quotes[key])
        # Report a quote problem once per base question, not once per translation
        if g.type == "answerable" and g.base_id not in reported_bases:
            reported_bases.add(g.base_id)
            refs = ", ".join(f"{r.source} p. {r.page}" for r in g.relevant_documents)
            if not any(matches):
                errors.append(f"{g.base_id}: supporting_text not found in {refs}")
            elif "exact" not in matches:
                warnings.append(f"{g.base_id}: supporting_text matched approximately in {refs}")

    by_lang = Counter(g.language for g in goldens)
    by_type = Counter(g.type for g in goldens)
    print(f"{len(goldens)} questions | {len({g.base_id for g in goldens})} base questions")
    print(f"  by language: {dict(by_lang)}")
    print(f"  by type    : {dict(by_type)}")
    print(f"  verified by a human: {sum(g.verified for g in goldens)}/{len(goldens)}")
    print(f"  documents referenced: {len({r.source for g in goldens for r in g.relevant_documents})}")
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print("OK" if not errors else f"{len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
