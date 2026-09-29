from openai import OpenAI

from app.config import settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """OpenAI-compatible client for the configured provider, created on first use.

    Creating it lazily means the app starts without any LLM key (setup problem S3).
    Groq speaks the OpenAI API, so only base_url and key differ. max_retries lets the SDK
    back off and retry on 429s, which the free Groq tier returns often.
    """
    global _client
    if _client is None:
        if settings.llm_provider == "groq":
            _client = OpenAI(api_key=settings.groq_api_key, base_url=GROQ_BASE_URL,
                             max_retries=settings.llm_max_retries)
        else:
            _client = OpenAI(api_key=settings.openai_api_key, max_retries=settings.llm_max_retries)
    return _client


def _extra_body(model: str) -> dict | None:
    # gpt-oss models think before answering; "low" keeps hidden reasoning tokens (which count
    # against the tokens-per-minute limit) small
    if model.startswith("openai/gpt-oss") and settings.llm_reasoning_effort:
        return {"reasoning_effort": settings.llm_reasoning_effort}
    return None


# Per-process counters for the eval runner: tokens per model (Groq free tier has a tokens-per-day
# budget) and API errors, because HyDE / CRAG / Self-RAG catch LLM errors and carry on silently
STATS: dict = {"tokens": {}, "errors": 0, "last_error": ""}


def _create(model: str, **kwargs):
    try:
        response = get_client().chat.completions.create(model=model, **kwargs)
    except Exception as exc:
        STATS["errors"] += 1
        STATS["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
        raise
    used = response.usage.total_tokens if response.usage else 0
    STATS["tokens"][model] = STATS["tokens"].get(model, 0) + used
    return response


def _usage(response) -> dict:
    return {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }


def generate(system_prompt: str, user_message: str, model: str | None = None, temperature: float = 0.0) -> dict:
    if model is None:
        model = settings.llm_model_answer

    response = _create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        extra_body=_extra_body(model),
    )

    text = response.choices[0].message.content or ""
    return {"text": text, "usage": _usage(response)}

def generate_with_json(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:

    if model is None:
        model = settings.llm_model_grader

    messages = [{"role": "system", "content": system_prompt}]
    if user_message:  # some callers put everything in the system prompt
        messages.append({"role": "user", "content": user_message})
    response = _create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
        extra_body=_extra_body(model),
    )
    text = response.choices[0].message.content or ""
    return {"text": text, "usage": _usage(response)}
