import threading

from loguru import logger

from app.config import settings
from app.services.query_cache_service import query_cache

_local_model = None
_local_lock = threading.Lock()
_openai_client = None


def _get_local_model():
    """Load the sentence-transformers model once (GPU + fp16 if CUDA is available)."""
    global _local_model
    if _local_model is None:
        with _local_lock:
            if _local_model is None:
                import torch
                from sentence_transformers import SentenceTransformer

                device = "cuda" if torch.cuda.is_available() else "cpu"
                model = SentenceTransformer(settings.embedding_model, device=device)
                if device == "cuda":
                    model.half()
                dim = model.get_embedding_dimension()
                if dim != settings.embedding_dim:
                    raise ValueError(
                        f"EMBEDDING_DIM={settings.embedding_dim} but {settings.embedding_model} "
                        f"produces {dim}-dim vectors; fix EMBEDDING_DIM in .env"
                    )
                logger.info("Loaded embedding model {} on {} (dim={})",
                            settings.embedding_model, device, dim)
                _local_model = model
    return _local_model


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _embed_uncached(texts: list[str], model: str) -> list[list[float]]:
    if settings.embedding_backend == "openai":
        response = _get_openai_client().embeddings.create(input=texts, model=model)
        return [item.embedding for item in response.data]
    vectors = _get_local_model().encode(
        texts, batch_size=16, normalize_embeddings=True, convert_to_numpy=True
    )
    return vectors.astype("float32").tolist()


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    if model is None:
        model = settings.embedding_model

    results: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int] = []
    miss_texts: list[str] = []

    for i, text in enumerate(texts):
        cached = query_cache.get_embedding(text, model)
        if cached is not None:
            results[i] = cached

        else:
            miss_indices.append(i)
            miss_texts.append(text)

    if miss_texts:
        vectors = _embed_uncached(miss_texts, model)
        for idx_in_misses, vector in enumerate(vectors):
            original_idx = miss_indices[idx_in_misses]
            results[original_idx] = vector
            query_cache.set_embedding(miss_texts[idx_in_misses], vector, model)

    return [r for r in results if r is not None]
