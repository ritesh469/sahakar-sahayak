"""P5: single routing when SQL is off, grounded multilingual prompt, page in spotlighting, CRAG
without web fallback. No LLM or network calls: the LLM-facing functions are stubbed."""

from app.config import settings
from app.models import RetrievedChunk
from app.security import system_prompt
from app.security.spotlighting import build_spotlighted_context
from app.services import crag, rag_service


def _chunk(text="PM-KISAN gives Rs 6,000 per year.", page=3):
    return RetrievedChunk(text=text, source="pmkisan_guidelines_en.pdf", page_number=page, score=0.9)


def test_sql_off_routes_to_rag_without_llm_call(monkeypatch):
    def fail(_question):
        raise AssertionError("router LLM must not be called when SQL is off")

    monkeypatch.setattr(settings, "sql_enabled", False)
    monkeypatch.setattr(rag_service, "classify_intent", fail)
    assert rag_service._route("How much does PM-KISAN pay?", None) == "rag"
    # a caller that already routed (the graph) is trusted: no second routing
    assert rag_service._route("anything", "hybrid") == "hybrid"


def test_system_prompt_has_rules_and_all_refusal_sentences():
    prompt = system_prompt.build_system_prompt()
    assert "Kubernetes" not in prompt and "JSON object" not in prompt
    for messages in (system_prompt.REFUSAL_MESSAGES, system_prompt.OUT_OF_DOMAIN_MESSAGES):
        assert set(messages) == {"en", "hi", "mr", "hinglish"}
        for sentence in messages.values():
            assert sentence in prompt
    assert "[file name, p. N]" in prompt


def test_spotlighting_shows_page_number():
    ctx = build_spotlighted_context([_chunk(page=3), _chunk(page=None)])
    assert 'source="pmkisan_guidelines_en.pdf" page="3"' in ctx
    # chunk without a page: no page attribute, not page="None"
    assert 'page="None"' not in ctx


def test_answer_language_follows_question(monkeypatch):
    seen = {}

    def fake_generate(system, user_msg, **_):
        seen["user_msg"] = user_msg
        return {"text": "PM-KISAN mein saal ke 6000 rupaye milte hain 【pmkisan_guidelines_en.pdf, p. 3】"}

    monkeypatch.setattr(rag_service, "generate", fake_generate)
    resp = rag_service._generate("PM-KISAN mein kitne paise milte hain?", [_chunk()])
    assert "Answer language: Hinglish" in seen["user_msg"]
    # full-width citation brackets are normalised to [ ]
    assert resp.answer.endswith("[pmkisan_guidelines_en.pdf, p. 3]")


def test_crag_irrelevant_chunks_dropped_without_web(monkeypatch):
    def no_web(_question):
        raise AssertionError("web search must not run when WEB_FALLBACK_ENABLED=false")

    monkeypatch.setattr(settings, "web_fallback_enabled", False)
    monkeypatch.setattr(crag, "search_web", no_web)
    monkeypatch.setattr(
        crag, "grade_chunks",
        lambda q, c: crag.CRAGEvaluation(relevance_score=0.1, relevance_label="incorrect",
                                         confidence=0.9, reasoning="off-topic"),
    )
    chunks, _, used_web = crag.crag_pipeline("cricket?", [_chunk()], enable_crag=True)
    assert chunks == [] and used_web is False
