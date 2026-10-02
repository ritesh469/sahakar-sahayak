"""The answer review sheet (eval/drafts/p10_answer_review.xlsx) decides which expected answers are
verified: Sahi -> approved, Galat -> corrected answer, empty -> not reviewed."""

import openpyxl
import pytest

from scripts.build_coop_questions import answer_review

HEADER = ["base_id", "Document", "Sawaal (English)", "Expected answer", "File, page",
          "Supporting text (PDF se)", "Sahi hai?", "Sahi jawab (sirf Galat par)", "Aapka note"]


def _sheet(tmp_path, rows):
    wb = openpyxl.Workbook()
    wb.active.title = "Kaise bharein"
    ws = wb.create_sheet("Answers")
    ws.append(HEADER)
    for base, verdict, fix in rows:
        ws.append([base, "", "", "", "", "", verdict, fix, None])
    path = tmp_path / "review.xlsx"
    wb.save(path)
    return path


def test_sahi_galat_and_empty_rows(tmp_path):
    path = _sheet(tmp_path, [("ans-001", "Sahi", None), ("ans-002", "Galat", "Rs 2 lakh per member."),
                             ("ans-003", None, None)])
    assert answer_review(path) == {"ans-001": None, "ans-002": "Rs 2 lakh per member."}


def test_galat_without_correction_stops_the_build(tmp_path):
    with pytest.raises(SystemExit, match="ans-004"):
        answer_review(_sheet(tmp_path, [("ans-004", "Galat", None)]))


def test_missing_sheet_means_nothing_verified(tmp_path):
    assert answer_review(tmp_path / "missing.xlsx") == {}
