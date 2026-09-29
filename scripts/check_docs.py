"""Check documents before ingestion (P3).

For every file prints: name, pages, language guess (Devanagari %), and the first 400
characters extracted by the SAME docling converter that ingestion uses. Files whose text
looks like garbage (almost no text, few letters, odd symbols, legacy Hindi font encoding,
lost pages) are marked SUSPICIOUS.

Usage:
  uv run --env-file .env python scripts/check_docs.py
  uv run --env-file .env python scripts/check_docs.py --write-sources      # sync data/sources.csv
  uv run --env-file .env python scripts/check_docs.py --pdf-backend docling_parse
  uv run --env-file .env python scripts/check_docs.py --dir seed/docs/_k8s_backup --limit 5
"""

import argparse
import csv
import logging
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "seed" / "docs" / "true_data"
SOURCES_CSV = ROOT / "data" / "sources.csv"
SOURCES_FIELDS = ["filename", "title", "source_url", "download_date", "language", "category"]
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}  # same as seed_db.py
PREVIEW_CHARS = 400

# Frequent words that tell Hindi and Marathi apart (both are Devanagari)
HINDI_MARKERS = {"है", "हैं", "और", "के", "में", "की", "से", "को", "का", "लिए", "यह", "किया"}
MARATHI_MARKERS = {"आहे", "आहेत", "आणि", "नाही", "किंवा", "करण्यात", "येते", "येईल", "त्यांना", "यांच्या"}
# Hindi typed in legacy fonts (Kruti Dev etc.) extracts as Latin garbage: के=ds, का=dk, की=dh,
# में=esa, है=gS, और=vkSj, से=ls, को=dks. In real English these tokens are rare.
LEGACY_FONT_MARKERS = {
    "ds", "dk", "dh", "esa", "gS", "gSA", "gSa", "vkSj", "ls", "dks", "Hkh", "ugha", "ljdkj", "Hkkjr",
}

MIN_CHARS = 200            # less than this = (almost) no text
MIN_CHARS_PER_PAGE = 100   # PDFs below this are probably scans that OCR could not read
MIN_LETTER_RATIO = 0.5     # Devanagari + Latin letters / all non-space chars
MAX_ODD_RATIO = 0.02       # replacement / private-use / control chars
MIN_LEGACY_RATIO = 0.03    # legacy-font marker tokens / Latin tokens
MAX_OTHER_SCRIPT = 0.05    # letters that are neither Devanagari nor Latin (e.g. Chinese from OCR)
MIN_EXPECTED_DEV = 0.2     # a hi/mr document (per sources.csv) needs at least this Devanagari share
MAX_BROKEN_DEV = 0.03      # WARN above this share of malformed Devanagari words

# Malformed Devanagari word: starts with a dependent sign (matra/virama/anusvara) or has two
# vowel signs in a row. Real Hindi/Marathi words never do; PDFs whose fonts map glyphs to the
# wrong Unicode characters (common in government PDFs made from Word) produce many of them,
# e.g. "भारि" for "भारत", "मकया" for "किया".
_DEV_WORD = re.compile(r"[\u0900-\u0963\u0966-\u097f\u200c\u200d]+")
_BROKEN_DEV = re.compile(r"^[\u0901-\u0903\u093e-\u094d]|[\u093e-\u094c]{2}")


def is_devanagari(ch: str) -> bool:
    return "\u0900" <= ch <= "\u097f" or "\ua8e0" <= ch <= "\ua8ff"


def is_odd(ch: str) -> bool:
    if ch in "\n\r\t":
        return False
    return ch == "\ufffd" or "\ue000" <= ch <= "\uf8ff" or unicodedata.category(ch) in {"Cc", "Co", "Cs"}


def analyze(text: str, pages: int, expected_lang: str = "") -> dict:
    chars = [c for c in text if not c.isspace()]
    n = len(chars)
    dev = sum(1 for c in chars if is_devanagari(c))
    latin = sum(1 for c in chars if c.isascii() and c.isalpha())
    other_letters = sum(1 for c in chars if c.isalpha() and not c.isascii() and not is_devanagari(c))
    odd = sum(1 for c in chars if is_odd(c)) + 5 * text.count("(cid:")
    letters = dev + latin + other_letters
    dev_pct = dev / letters if letters else 0.0

    words = re.findall(r"\S+", text)
    dev_words = Counter(w.strip("।,.;:()[]\"'") for w in words if any(is_devanagari(c) for c in w))
    latin_words = [w.strip(",.:()[]\"'") for w in words if w.isascii() and any(c.isalpha() for c in w)]
    legacy_hits = sum(1 for w in latin_words if w in LEGACY_FONT_MARKERS)

    if dev_pct >= 0.6:
        hi = sum(dev_words[w] for w in HINDI_MARKERS)
        mr = sum(dev_words[w] for w in MARATHI_MARKERS) + text.count("ळ")
        lang = "mr" if mr > hi else "hi"
    elif dev_pct <= 0.1:
        lang = "en"
    else:
        lang = "mixed"

    reasons = []
    if n < MIN_CHARS:
        reasons.append(f"almost no text ({n} chars)")
    elif pages and n / pages < MIN_CHARS_PER_PAGE:
        reasons.append(f"little text per page ({n // pages}/page, scanned?)")
    if n and letters / n < MIN_LETTER_RATIO:
        reasons.append(f"few letters ({letters / n:.0%})")
    if n and odd / n > MAX_ODD_RATIO:
        reasons.append(f"odd symbols ({odd / n:.1%})")
    if len(latin_words) >= 50 and legacy_hits / len(latin_words) >= MIN_LEGACY_RATIO:
        reasons.append(f"legacy Hindi font? ({legacy_hits} tokens like 'ds','esa','gS')")
    # RapidOCR's Chinese/English models turn scanned Devanagari into Chinese characters
    if letters and other_letters / letters > MAX_OTHER_SCRIPT:
        reasons.append(f"unexpected script ({other_letters / letters:.0%} of letters are not "
                       "Devanagari/Latin, OCR garbage?)")
    if expected_lang in ("hi", "mr") and dev_pct < MIN_EXPECTED_DEV:
        reasons.append(f"sources.csv says '{expected_lang}' but only {dev_pct:.0%} Devanagari")

    # Usable but degraded: reported as a warning, not SUSPICIOUS
    dev_tokens = _DEV_WORD.findall(text)
    broken = sum(1 for w in dev_tokens if _BROKEN_DEV.search(w)) / len(dev_tokens) if dev_tokens else 0.0
    warnings = []
    if len(dev_tokens) >= 50 and broken > MAX_BROKEN_DEV:
        warnings.append(f"damaged Devanagari text layer ({broken:.0%} of words malformed, "
                        "PDF font encoding): Hindi/Marathi retrieval will suffer")

    return {"chars": n, "dev_pct": dev_pct, "lang": lang, "reasons": reasons,
            "broken_dev_pct": broken, "warnings": warnings}


def collect_files(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and p.name != ".gitkeep"
    )


def read_source_languages() -> dict[str, str]:
    """filename -> language from data/sources.csv (empty if the file does not exist)."""
    if not SOURCES_CSV.exists():
        return {}
    with SOURCES_CSV.open(encoding="utf-8-sig", newline="") as f:
        return {r["filename"]: (r.get("language") or "").strip() for r in csv.DictReader(f)}


def write_sources(files: list[Path]) -> None:
    """Add missing filenames to data/sources.csv; rows you already filled are kept as they are."""
    rows: list[dict] = []
    if SOURCES_CSV.exists():
        with SOURCES_CSV.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    known = {r["filename"] for r in rows}
    added = [p.name for p in files if p.name not in known]
    rows += [{"filename": name} for name in added]

    SOURCES_CSV.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel shows Hindi/Marathi titles correctly
    with SOURCES_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=SOURCES_FIELDS, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    present = {p.name for p in files}
    stale = [r["filename"] for r in rows if r["filename"] not in present]
    print(f"\n{SOURCES_CSV.relative_to(ROOT)}: {len(rows)} rows ({len(added)} new)")
    if stale:
        print(f"  WARNING: in sources.csv but not in the folder: {stale}")


def main() -> None:
    # Windows console is cp1252 (setup problem S6); line buffering shows progress when redirected
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    parser = argparse.ArgumentParser(description="Check documents before ingestion")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder to check")
    parser.add_argument("--limit", type=int, default=0, help="only the first N files (0 = all)")
    parser.add_argument("--pdf-backend", choices=["pypdfium2", "docling_parse"],
                        help="override PDF_BACKEND to compare extraction")
    parser.add_argument("--write-sources", action="store_true",
                        help="add missing filenames to data/sources.csv")
    args = parser.parse_args()

    from app.config import settings

    if args.pdf_backend:
        settings.pdf_backend = args.pdf_backend
    # docling/RapidOCR log every model load at INFO (RapidOCR resets its own logger level)
    logging.disable(logging.INFO)

    files = collect_files(args.dir)
    expected = read_source_languages()
    if not files:
        print(f"No documents found in {args.dir}")
        if args.write_sources:
            write_sources(files)
        return
    if args.limit:
        files = files[: args.limit]

    from app.services.document_processor import DocumentProcessor
    from app.services.text_cleaning import clean_extracted_text

    # Same converter + on-disk cache as ingestion, so ingestion reuses these conversions
    processor = DocumentProcessor()
    print(f"Checking {len(files)} files in {args.dir} (PDF_BACKEND={settings.pdf_backend})\n")

    results = []
    for i, path in enumerate(files, start=1):
        t0 = time.time()
        try:
            doc, conv = processor.convert(path)
            pages = doc.num_pages()
            text = clean_extracted_text(doc.export_to_text())  # what ingestion indexes
            info = analyze(text, pages, expected.get(path.name, ""))
            if conv["status"] != "success":
                info["reasons"].insert(
                    0, f"conversion {conv['status']}, pages missing {conv['missing_pages']}"
                )
            preview = " ".join(text.split())[:PREVIEW_CHARS]
        except Exception as exc:  # noqa: BLE001
            pages, preview = 0, ""
            info = {"chars": 0, "dev_pct": 0.0, "lang": "?", "broken_dev_pct": 0.0, "warnings": [],
                    "reasons": [f"conversion failed: {type(exc).__name__}: {exc}"]}

        status = "SUSPICIOUS" if info["reasons"] else ("WARN" if info["warnings"] else "OK")
        results.append((path.name, status, info))
        print(f"[{i}/{len(files)}] {path.name}")
        print(f"    pages={pages or '-'}  chars={info['chars']:,}  lang={info['lang']}  "
              f"Devanagari={info['dev_pct']:.0%}  broken={info['broken_dev_pct']:.0%}  "
              f"({time.time() - t0:.1f}s)  {status}")
        for reason in info["reasons"]:
            print(f"    ! {reason}")
        for warning in info["warnings"]:
            print(f"    ~ {warning}")
        print(f"    text: {preview}\n")

    langs = Counter(info["lang"] for _, _, info in results)
    suspicious = [(name, info["reasons"]) for name, status, info in results if status == "SUSPICIOUS"]
    warned = [(name, info) for name, status, info in results if status == "WARN"]
    print("=" * 70)
    print(f"{len(results)} files | languages: {dict(langs)} | SUSPICIOUS: {len(suspicious)} "
          f"| WARN: {len(warned)}")
    for name, reasons in suspicious:
        print(f"  SUSPICIOUS  {name}: {'; '.join(reasons)}")
    for name, info in warned:
        print(f"  WARN        {name}: {info['broken_dev_pct']:.0%} malformed Devanagari words")

    if args.write_sources:
        write_sources(collect_files(args.dir))


if __name__ == "__main__":
    main()
