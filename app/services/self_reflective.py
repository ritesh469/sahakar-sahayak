
import json
import logging

from app.config import settings
from app.models import ReflectionResult
from app.services.llm_service import generate_with_json


# Original prompt (kept for the P16 comparison, SELF_RAG_PROMPT=original). It treats every
# refusal as a failure and asks for a regeneration, which pushes the model to answer questions
# the documents cannot answer (CLAUDE.md Known problem #11).
_REFLECTION_PROMPT_ORIGINAL = """You are a strict reviewer evaluating an AI-generated answer.
Your job is to FAIL answers that don't deliver real value to the user.

User Question: {question}

Generated Answer: {answer}

Retrieved Context (if any): {context}

Score each criterion 1-10. BE STRICT — do not give pity points.

1. Relevance (1-10):
   - 10: Directly answers the question with concrete content.
   - 5 or below: Hedges, refuses, or gives only meta-commentary
     ("The retrieved context does not provide...", "I don't have information...",
     "It depends...", "Many things could be meant by this...").
   - 3 or below: Off-topic or talks about unrelated subjects from the context.

2. Accuracy (1-10):
   - 10: All claims are grounded in the retrieved context and are factually correct.
   - 5 or below: Some claims are unsupported by the context.
   - 3 or below: The answer contradicts the context or invents facts.

3. Completeness (1-10):
   - 10: Addresses every part of the question with sufficient depth.
   - 5 or below: Misses major parts of the question, or is too short to be useful
     (e.g. one sentence answers to a multi-part technical question).
   - 3 or below: Effectively a non-answer ("I don't know", "see the documentation").

4. Clarity (1-10):
   - 10: Well-structured, easy to follow, uses examples where helpful.
   - 5 or below: Disorganised, jargon-heavy, or confusing.

Overall reflection_score = average of the four criteria / 10.0 (range 0.0–1.0).

needs_regeneration is True if ANY of the following hold:
- The answer is a hedge or refusal ("does not provide", "I don't have", "unclear").
- Relevance or Completeness scored 5 or below.
- The overall score is below 0.85.
- The question is vague/ambiguous and a SHARPER reformulation would clearly help.

When needs_regeneration is True, set refined_question to a fully self-contained,
single-sentence reformulation of the user's question that adds the missing
specificity (e.g. add domain context, name the entity, narrow the timeframe).

Respond ONLY with a JSON object — no prose before or after:
{{"reflection_score": float, "needs_regeneration": bool, "refined_question": str, "reasoning": str}}
"""


# Default (P16): a refusal is a good answer when the context really does not contain the answer
_REFLECTION_PROMPT_REFUSAL_AWARE = """You are a strict reviewer evaluating an answer from a
cooperative-governance / government-scheme assistant. The assistant must answer ONLY from the
retrieved context. When the context does not contain the answer it must refuse with a fixed
"not found in the documents" sentence; for questions outside its domain it politely declines.

User Question: {question}

Generated Answer: {answer}

Retrieved Context (if any): {context}

First decide: does the retrieved context actually contain the information needed to answer?

Score each criterion 1-10. BE STRICT — do not give pity points.

1. Relevance (1-10):
   - 10: Directly answers the question with concrete content from the context, OR correctly
     refuses because the context does not contain the answer (or the question is out of domain).
   - 5 or below: Refuses or hedges although the context DOES contain the answer.
   - 3 or below: Off-topic or talks about unrelated subjects from the context.

2. Accuracy (1-10):
   - 10: Every claim is supported by the retrieved context (a correct refusal claims nothing).
   - 5 or below: Some claims are not supported by the context.
   - 1: The answer invents facts, numbers, dates or names that are not in the context, or
     accepts a false premise in the question. Inventing an answer is worse than refusing.

3. Completeness (1-10):
   - 10: Addresses every part of the question that the context can answer (a correct refusal
     is complete).
   - 5 or below: Misses parts of the question that the context does answer.

4. Clarity (1-10):
   - 10: Well-structured and easy to follow.
   - 5 or below: Disorganised or confusing.

Overall reflection_score = average of the four criteria / 10.0 (range 0.0–1.0).

needs_regeneration is True ONLY if:
- the answer refuses or hedges although the context contains the answer, or
- the answer contains claims that are not supported by the context, or
- the overall score is below 0.85 for another concrete reason.
A correct refusal (the context does not contain the answer) is a GOOD answer:
needs_regeneration = False. Never ask for a regeneration just to get a longer answer.

When needs_regeneration is True, set refined_question to a fully self-contained,
single-sentence reformulation of the user's question (e.g. name the scheme or the Act).

Respond ONLY with a JSON object — no prose before or after:
{{"reflection_score": float, "needs_regeneration": bool, "refined_question": str, "reasoning": str}}
"""

_PROMPTS = {"original": _REFLECTION_PROMPT_ORIGINAL, "refusal_aware": _REFLECTION_PROMPT_REFUSAL_AWARE}


def reflect_on_answer(
    question: str,
    answer: str,
    context: str = "",
) -> ReflectionResult:
    try:
        formatted_prompt = _PROMPTS[settings.self_rag_prompt].format(
            question=question,
            answer=answer,
            context=context,
        )
        response = generate_with_json(
            system_prompt=formatted_prompt,
            user_message="",
            model=settings.llm_model_grader,
            temperature=0.0,
        )
        parsed = json.loads(response["text"])
        return ReflectionResult(**parsed)
    except Exception as exc:
        logging.error("Reflection failed: %s", exc)
        return ReflectionResult(
            reflection_score=1.0,
            needs_regeneration=False,
            refined_question="",
            reasoning="Reflection failed, accepting answer as-is",
        )


def should_regenerate(reflection: ReflectionResult, iteration: int) -> bool:
    return (
        reflection.needs_regeneration
        and reflection.reflection_score < settings.reflection_min_score
        and iteration < settings.max_reflection_retries
    )
