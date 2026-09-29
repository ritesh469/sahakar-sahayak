"""P16: Self-RAG reviewer prompt choice (Known problem #11, refusal bias)."""

import json

from app.config import settings
from app.services import self_reflective


def _capture(monkeypatch):
    seen = {}

    def fake(system_prompt, user_message, model=None, temperature=0.0):
        seen["prompt"] = system_prompt
        return {"text": json.dumps({"reflection_score": 0.9, "needs_regeneration": False,
                                    "refined_question": "", "reasoning": "ok"})}

    monkeypatch.setattr(self_reflective, "generate_with_json", fake)
    return seen


def test_default_prompt_accepts_correct_refusal(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setattr(settings, "self_rag_prompt", "refusal_aware")
    self_reflective.reflect_on_answer("What is the helpline number?", "Not in the documents.", "ctx")
    assert "A correct refusal (the context does not contain the answer) is a GOOD answer" in seen["prompt"]
    assert "Inventing an answer is worse than refusing" in seen["prompt"]


def test_original_prompt_still_available(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setattr(settings, "self_rag_prompt", "original")
    self_reflective.reflect_on_answer("q", "I don't have information", "ctx")
    assert "The answer is a hedge or refusal" in seen["prompt"]


def test_default_setting_is_refusal_aware():
    assert type(settings).model_fields["self_rag_prompt"].default == "refusal_aware"
