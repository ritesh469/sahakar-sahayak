from __future__ import annotations

from datasets import Dataset
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from ragas import RunConfig, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from app.config import settings

# Groq serves one completion per request (n must be 1); answer_relevancy asks for `strictness`
# generated questions in a single call, so keep it at 1
answer_relevancy.strictness = 1

METRICS = [
    faithfulness,
    context_precision,
    context_recall,
    answer_relevancy,
]


class _LocalEmbeddings(Embeddings):
    """LangChain wrapper around the app's embedding model (bge-m3 on the GPU)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from app.services.embedding_service import embed_texts

        return embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _get_ragas_llm():
    """Judge LLM = the grader model on the configured provider (Groq by default)."""
    from app.services.llm_service import GROQ_BASE_URL

    if settings.llm_provider == "groq":
        chat = ChatOpenAI(model=settings.llm_model_grader, api_key=settings.groq_api_key,
                          base_url=GROQ_BASE_URL, temperature=0, max_retries=settings.llm_max_retries)
    else:
        # Use a non-reasoning judge (e.g. gpt-4.1*): Ragas sets the temperature on every call,
        # which OpenAI reasoning models reject
        chat = ChatOpenAI(model=settings.llm_model_grader, api_key=settings.openai_api_key,
                          temperature=0, max_retries=settings.llm_max_retries)
    return LangchainLLMWrapper(chat)

def _get_ragas_embeddings():
    """Ragas embeddings (answer_relevancy) = the same local model used for retrieval."""
    return LangchainEmbeddingsWrapper(_LocalEmbeddings())

def build_dataset(rows: list[dict]) -> Dataset:
    return Dataset.from_dict(
        {
            "user_input": [r["question"] for r in rows],
            "response": [r["answer"] for r in rows],
            "retrieved_contexts": [r["contexts"] for r in rows],
            "reference": [r["ground_truth"] for r in rows],
        }
    )

def run(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    ds = build_dataset(rows)
    result = evaluate(
        ds,
        metrics=METRICS,
        llm=_get_ragas_llm(),
        embeddings=_get_ragas_embeddings(),
        # few parallel calls + long waits: Groq free tier allows ~8k tokens/min per model
        run_config=RunConfig(max_workers=2, max_wait=90, max_retries=12, timeout=300),
        raise_exceptions=False,
        show_progress=False,
    )
    return result.to_pandas().to_dict(orient="records")
