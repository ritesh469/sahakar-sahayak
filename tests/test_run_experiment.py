"""Runner helpers: Groq daily-limit detection and the answerable sample (free-tier budget)."""

import pytest

from eval.run_experiment import DailyLimitReached, _is_daily_limit, sample_answerable, with_rate_limit_retry
from eval.schema import CoopGolden


def q(base_id, lang="en", type_="answerable"):
    extra = {"expected_answer": "x", "supporting_text": "x", "relevant_documents": [{"source": "a.pdf"}]}
    return CoopGolden(id=f"{base_id}-{lang}", base_id=base_id, language=lang, type=type_,
                      question="What is it?", **(extra if type_ == "answerable" else {}))


def test_daily_limit_messages():
    tpd = ("Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b` in organization org_x "
           "service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199500, Requested 2900.")
    tpm = "Error code: 429 - Rate limit reached ... on tokens per minute (TPM): Limit 8000, Used 7000"
    assert _is_daily_limit(tpd)
    assert _is_daily_limit("... on requests per day (RPD): Limit 1000, Used 1000")
    assert not _is_daily_limit(tpm)


def test_daily_limit_is_not_retried():
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("429 Rate limit reached on tokens per day (TPD)")

    with pytest.raises(DailyLimitReached):
        with_rate_limit_retry(fail, wait_s=0)
    assert len(calls) == 1


def test_other_errors_are_raised_unchanged():
    def fail():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        with_rate_limit_retry(fail, wait_s=0)


def test_sample_answerable_keeps_all_languages_and_non_answerable():
    goldens = [q(f"ans-{i:03d}", lang) for i in range(1, 11) for lang in ("en", "hi")]
    goldens += [q("unans-001", "mr", "unanswerable")]
    picked = sample_answerable(goldens, 3)
    bases = sorted({g.base_id for g in picked if g.type == "answerable"})
    assert bases == ["ans-001", "ans-005", "ans-010"]  # first, middle (index 4.5 -> 4), last
    assert len([g for g in picked if g.type == "answerable"]) == 6  # both languages
    assert any(g.base_id == "unans-001" for g in picked)


def test_sample_answerable_no_op_when_large():
    goldens = [q(f"ans-{i:03d}") for i in range(1, 4)]
    assert sample_answerable(goldens, 10) == goldens
    assert sample_answerable(goldens, 0) == goldens
