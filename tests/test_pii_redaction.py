"""PII redaction must not use llm-guard's English PERSON NER unless enabled: it tagged Devanagari
words ("किसान", "महिला शेतकरी") as names and the redacted question no longer matched the documents."""

import sys
import types

from app.config import settings
from app.security import content_moderation


class _FakeSensitive:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _entity_types(monkeypatch, person_names: bool) -> list[str]:
    fake = types.ModuleType("llm_guard.output_scanners")
    fake.Sensitive = _FakeSensitive
    monkeypatch.setitem(sys.modules, "llm_guard.output_scanners", fake)
    monkeypatch.setattr(settings, "pii_redact_person_names", person_names)
    monkeypatch.setattr(content_moderation, "_pii_scanners", None)
    return content_moderation._get_pii_scanners()[0].kwargs["entity_types"]


def test_person_names_not_redacted_by_default(monkeypatch):
    types_ = _entity_types(monkeypatch, person_names=False)
    assert "PERSON" not in types_
    assert {"EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"} <= set(types_)


def test_person_names_can_be_enabled_for_comparison(monkeypatch):
    assert "PERSON" in _entity_types(monkeypatch, person_names=True)
