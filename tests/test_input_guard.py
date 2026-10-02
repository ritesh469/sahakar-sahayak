"""llm-guard's PromptInjection model is English-only: in the P14 security test it blocked 8 of 16
normal Hindi/Marathi questions. It must be skipped for Devanagari questions unless
PROMPT_INJECTION_SCAN_DEVANAGARI=true, and still run for English and Hinglish."""

import sys
import types

import pytest

from app.config import settings
from app.security import input_guard


def _fake_scanner(name):
    return type(name, (), {"__init__": lambda self, **kwargs: None})


@pytest.fixture
def scanned(monkeypatch):
    """Run scan_input with fake llm-guard scanners; return the scanner names used per call."""
    fake = types.ModuleType("llm_guard.input_scanners")
    for name in ("PromptInjection", "Toxicity", "BanTopics", "TokenLimit"):
        setattr(fake, name, _fake_scanner(name))
    monkeypatch.setitem(sys.modules, "llm_guard.input_scanners", fake)
    monkeypatch.setattr(input_guard, "_scanners", None)

    def fake_scan_prompt(scanners, text):
        names = [type(s).__name__ for s in scanners]
        return text, {n: True for n in names}, {n: 0.0 for n in names}

    monkeypatch.setattr(input_guard, "_SCAN_PROMPT", fake_scan_prompt)
    return lambda text: list(input_guard.scan_input(text)["scores"])


@pytest.mark.parametrize("question", [
    "पीएम-किसान के लिए ओटीपी आधारित ई-केवाईसी करने के लिए किसान के पास क्या होना चाहिए?",
    "सहकारी लोकपालाकडे तक्रार करण्यापूर्वी सदस्याने काय करणे आवश्यक आहे?",
])
def test_devanagari_skips_english_injection_model(scanned, monkeypatch, question):
    monkeypatch.setattr(settings, "prompt_injection_scan_devanagari", False)
    assert scanned(question) == ["Toxicity", "BanTopics", "TokenLimit"]


@pytest.mark.parametrize("question", [
    "What must a farmer have for OTP-based e-KYC under PM-KISAN?",
    "PM-KISAN ke liye OTP wala e-KYC karne ke liye kisan ke paas kya hona chahiye?",
])
def test_english_and_hinglish_keep_injection_model(scanned, monkeypatch, question):
    monkeypatch.setattr(settings, "prompt_injection_scan_devanagari", False)
    assert "PromptInjection" in scanned(question)


def test_old_behaviour_can_be_enabled_for_comparison(scanned, monkeypatch):
    monkeypatch.setattr(settings, "prompt_injection_scan_devanagari", True)
    assert "PromptInjection" in scanned("सहकारी लोकपालाकडे तक्रार करण्यापूर्वी सदस्याने काय करावे?")
