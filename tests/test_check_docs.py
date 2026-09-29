"""P3: language guess + SUSPICIOUS heuristics of scripts/check_docs.py on hand-made samples."""

import csv

from scripts import check_docs
from scripts.check_docs import analyze

HINDI = (
    "प्रधानमंत्री फसल बीमा योजना किसानों को फसल के नुकसान से सुरक्षा देती है। "
    "इस योजना में किसान को कम प्रीमियम देना होता है और बाकी राशि सरकार देती है। "
) * 3
MARATHI = (
    "प्रधानमंत्री पीक विमा योजना ही शेतकऱ्यांसाठी आहे. या योजनेत शेतकऱ्यांना कमी हप्ता "
    "भरावा लागतो आणि उर्वरित रक्कम सरकार भरते. नुकसान झाल्यास भरपाई दिली जाते. "
) * 3
ENGLISH = (
    "Pradhan Mantri Fasal Bima Yojana provides crop insurance to farmers. Farmers pay a "
    "low premium and the government pays the rest of the premium amount. "
) * 3
# The HINDI text above typed in Kruti Dev and extracted as-is from a PDF
KRUTI_DEV = (
    "iz/kkuea=h Qly chek ;kstuk fdlkuksa dks Qly ds uqdlku ls lqj{kk nsrh gSA "
    "bl ;kstuk esa fdlku dks de izhfe;e nsuk gksrk gS vkSj ckdh jkf'k ljdkj nsrh gSA "
) * 3


def test_hindi_detected():
    info = analyze(HINDI, pages=1)
    assert info["lang"] == "hi"
    assert info["dev_pct"] > 0.95
    assert info["reasons"] == []


def test_marathi_detected():
    info = analyze(MARATHI, pages=1)
    assert info["lang"] == "mr"
    assert info["reasons"] == []


def test_english_detected():
    info = analyze(ENGLISH, pages=1)
    assert info["lang"] == "en"
    assert info["reasons"] == []


def test_mixed_hindi_english():
    assert analyze(HINDI + ENGLISH, pages=1)["lang"] == "mixed"


def test_legacy_font_is_suspicious():
    info = analyze(KRUTI_DEV, pages=1)
    assert any("legacy Hindi font" in r for r in info["reasons"])


def test_scan_without_text_is_suspicious():
    info = analyze("12 / 2024", pages=5)
    assert any("almost no text" in r for r in info["reasons"])


def test_little_text_per_page_is_suspicious():
    info = analyze(ENGLISH, pages=20)
    assert any("little text per page" in r for r in info["reasons"])


def test_odd_symbols_are_suspicious():
    info = analyze(ENGLISH + "\ufffd\ue001" * 40, pages=1)
    assert any("odd symbols" in r for r in info["reasons"])


def test_few_letters_is_suspicious():
    info = analyze("# $ % & * + = | ~ 1 2 3 4 5 6 7 8 9 0 " * 20, pages=1)
    assert any("few letters" in r for r in info["reasons"])


def test_ocr_chinese_garbage_is_suspicious():
    # What RapidOCR's Chinese model made of a scanned Marathi press note
    garbage = '"Hgg 打e Hght e" 可gt famaf 3eeeadg a市 e e he E 打j时 打 可 R 可时 3n。 付g 物可可讨 ' * 5
    info = analyze(garbage, pages=1)
    assert any("unexpected script" in r for r in info["reasons"])


def test_expected_devanagari_but_latin_text():
    info = analyze(ENGLISH, pages=1, expected_lang="mr")
    assert any("sources.csv says 'mr'" in r for r in info["reasons"])
    assert analyze(MARATHI, pages=1, expected_lang="mr")["reasons"] == []
    assert analyze(ENGLISH, pages=1, expected_lang="en")["reasons"] == []


def test_damaged_devanagari_text_layer_is_a_warning():
    # Extracted text of grain_storage_plan_sop_hi.pdf p. 6: the PDF maps glyphs to wrong
    # characters ("भारि" = भारत, "सिय" = समय, "मकया" = किया, "िें" = में)
    damaged = ("भारि ने लंबे सिय से खाद्यान् न भंडारण की किी से संबंमधि चुनौमियों का सािना "
               "मकया है मजसिें क्षििा की किी सहकाररिा क्षेत्र िें मवश् व की सबसे बडी िई ") * 3
    info = analyze(damaged, pages=1)
    assert info["reasons"] == []  # still usable text, so not SUSPICIOUS
    assert info["broken_dev_pct"] > 0.03
    assert any("damaged Devanagari" in w for w in info["warnings"])
    clean = analyze(HINDI + MARATHI, pages=1)
    assert clean["broken_dev_pct"] == 0.0 and clean["warnings"] == []


def test_write_sources_keeps_filled_rows(tmp_path, monkeypatch):
    sources = tmp_path / "data" / "sources.csv"
    monkeypatch.setattr(check_docs, "SOURCES_CSV", sources)
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    sources.parent.mkdir()
    sources.write_text(
        "filename,title,source_url,download_date,language,category\n"
        "a.pdf,A title,https://example.gov.in/a.pdf,2026-09-01,hi,scheme\n",
        encoding="utf-8",
    )
    (tmp_path / "a.pdf").touch()
    (tmp_path / "b.pdf").touch()

    check_docs.write_sources([tmp_path / "a.pdf", tmp_path / "b.pdf"])

    with sources.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["filename"] for r in rows] == ["a.pdf", "b.pdf"]
    assert rows[0]["source_url"] == "https://example.gov.in/a.pdf"  # user data kept
    assert rows[1]["title"] == ""
