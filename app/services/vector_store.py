from __future__ import annotations

import threading
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings
from app.models import RetrievedChunk


def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, timeout=30)

def collection_name(chunk_size: int | None = None) -> str:
    """One collection per chunk size, so chunking experiments never overwrite each other."""
    return f"{settings.qdrant_collection_prefix}_{chunk_size or settings.chunk_size}"

def _point_id(chunk: RetrievedChunk) -> str:
    # Deterministic id: re-ingesting the same document overwrites instead of duplicating
    key = f"{chunk.source}\x00{chunk.page_number}\x00{chunk.text}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))

def _to_chunk(payload: dict | None, score: float = 0.0) -> RetrievedChunk:
    payload = payload or {}
    return RetrievedChunk(
        text=payload.get("text", ""),
        source=payload.get("source", ""),
        page_number=payload.get("page_number"),
        score=score,
    )

def ensure_collection(collection: str | None = None) -> None:
    collection = collection or collection_name()
    client = get_client()

    if client.collection_exists(collection):
        size = getattr(client.get_collection(collection).config.params.vectors, "size", None)
        if size != settings.embedding_dim:
            raise ValueError(
                f"Collection {collection!r} has vector size {size}, but EMBEDDING_DIM="
                f"{settings.embedding_dim}; re-ingest with --recreate or use another prefix"
            )
        return

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
    )

def recreate_collection(collection: str | None = None) -> None:
    collection = collection or collection_name()
    client = get_client()
    if client.collection_exists(collection):
        client.delete_collection(collection)
    invalidate_sparse_cache(collection)
    ensure_collection(collection)

def upsert_chunks(
    chunks: list[RetrievedChunk],
    embeddings: list[list[float]],
    collection: str | None = None,
) -> None:
    collection = collection or collection_name()
    ensure_collection(collection)
    client  = get_client()
    points = [
        PointStruct(
            id=_point_id(chunk),
            vector=embedding,
            payload={"text": chunk.text, "source": chunk.source, "page_number": chunk.page_number},
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    client.upsert(collection_name=collection, points=points)
    invalidate_sparse_cache(collection)

def search(
    query_embedding: list[float], top_k: int = 5, collection: str | None = None
) -> list[RetrievedChunk]:
    client = get_client()
    results = client.query_points(
        collection_name=collection or collection_name(),
        query=query_embedding,
        limit=top_k,
        with_payload=True,
    ).points

    return [_to_chunk(p.payload, float(p.score)) for p in results]


SPARSE_KINDS = ("bm25", "tfidf")

# Sparse indexes built once per (kind, collection) and kept in memory (Known problem #1: the
# index used to be rebuilt from a full Qdrant scroll on every query). upsert/recreate drop the
# entries of that collection so the next query rebuilds from the new contents.
_sparse_cache: dict[tuple[str, str], object] = {}
_sparse_lock = threading.Lock()


def _scroll_all(collection: str, page_size: int = 1000) -> list[dict]:
    """Every chunk of the collection (paginated: a single scroll(limit=10000) silently dropped
    everything after the first 10k points)."""
    client = get_client()
    documents: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection, limit=page_size, offset=offset,
            with_payload=True, with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            documents.append({
                "text": payload.get("text", ""),
                "source": payload.get("source", ""),
                "page_number": payload.get("page_number"),
                "id": str(point.id),
            })
        if offset is None:
            return documents


def _build_sparse_index(collection: str | None = None, kind: str = "bm25"):
    from app.services.sparse_vector_service import BM25Index, SparseVectorIndex

    if kind not in SPARSE_KINDS:
        raise ValueError(f"unknown sparse index {kind!r}; expected one of {SPARSE_KINDS}")
    index = BM25Index() if kind == "bm25" else SparseVectorIndex()
    index.fit(_scroll_all(collection or collection_name()))
    return index


def get_sparse_index(collection: str | None = None, kind: str = "bm25"):
    """Cached sparse index for the collection (built on first use)."""
    key = (kind, collection or collection_name())
    with _sparse_lock:
        if key not in _sparse_cache:
            _sparse_cache[key] = _build_sparse_index(key[1], kind)
        return _sparse_cache[key]


def invalidate_sparse_cache(collection: str | None = None) -> None:
    """Drop cached sparse indexes of one collection (all collections if None)."""
    with _sparse_lock:
        for key in [k for k in _sparse_cache if collection is None or k[1] == collection]:
            del _sparse_cache[key]


def sparse_search(
    query_text: str, top_k: int = 5, collection: str | None = None, kind: str = "bm25"
) -> list[RetrievedChunk]:
    """Keyword search only: BM25 (default) or the original TF-IDF baseline."""
    return get_sparse_index(collection, kind).search(query_text, top_k=top_k)


def hybrid_search(
    query_embedding: list[float],
    query_text: str,
    top_k: int = 5,
    rrf_k: int = 60,
    sparse_top_k: int = 20,
    collection: str | None = None,
    sparse_kind: str = "bm25",
) -> list[RetrievedChunk]:
    """Dense + sparse (BM25 by default), fused with Reciprocal Rank Fusion."""
    from app.services.sparse_vector_service import fuse_rrf

    dense_results = search(query_embedding, top_k=sparse_top_k, collection=collection)
    sparse_results = sparse_search(query_text, top_k=sparse_top_k, collection=collection,
                                   kind=sparse_kind)
    fused = fuse_rrf([dense_results, sparse_results], rrf_k=rrf_k)
    return fused[:top_k]
