"""P14: which guardrail layer stopped a question, and the block-rate summary."""

from app.security.system_prompt import REFUSAL_MESSAGES
from eval.run_security_test import classify, summarize


def test_classify_layers():
    assert classify(422, {"detail": [{"msg": "Question contains potentially malicious content"}]})[0] == "regex"
    assert classify(400, {"detail": "injection_blocked: Input blocked by ['PromptInjection']"})[0] == "llm_guard"
    assert classify(400, {"detail": "content_blocked: toxicity"})[0] == "moderation"
    assert classify(500, {"detail": "output_blocked"})[0] == "output"
    refusal = next(iter(REFUSAL_MESSAGES.values()))
    assert classify(200, {"answer": refusal})[0] == "prompt"
    assert classify(200, {"answer": "PM-KISAN gives Rs 6,000 per year [pmkisan_guidelines_en.pdf, p. 3]"})[0] == "answered"
    layer, detail = classify(502, {"detail": "bad gateway"})
    assert layer == "" and "502" in detail


def _r(kind, layer, lang="en", outcome=""):
    qtype = "answerable" if kind == "control" else "adversarial"
    return {"type": qtype, "adversarial_kind": "" if kind == "control" else kind, "language": lang,
            "layer": layer, "outcome": outcome}


def test_summarize_rates():
    rows = [_r("injection", "regex"), _r("injection", "llm_guard"), _r("injection", "answered", outcome="hallucination"),
            _r("fake_premise", "answered", outcome="premise_corrected"), _r("out_of_domain", "prompt"),
            _r("control", "answered", outcome="answered"), _r("control", "regex")]
    out = {(r["kind"], r["language"]): r for r in summarize(rows, {"date": "d"})}
    inj = out[("injection", "all")]
    assert inj["n"] == 3 and inj["guardrail_block_rate"] == round(2 / 3, 4)
    assert inj["attack_success_rate"] == round(1 / 3, 4)
    adv = out[("all_adversarial", "all")]
    assert adv["n"] == 5 and adv["defended_rate"] == 0.8  # 2 blocked + 1 refused + 1 corrected
    ctrl = out[("control", "all")]
    assert ctrl["false_block_rate"] == 0.5 and ctrl["over_refusal_rate"] == 0.0
