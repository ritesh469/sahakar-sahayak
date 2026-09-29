from __future__ import annotations

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


def _build_sparse_index(collection: str | None = None):
    from app.services.sparse_vector_service import SparseVectorIndex
    client = get_client()
    all_points, _next_page = client.scroll(
        collection_name=collection or collection_name(),
        limit=10000,
        with_payload=True,
        with_vectors=False,
    )
    documents = [
        {
            "text": point.payload.get("text", "") if point.payload else "",
            "source": point.payload.get("source", "") if point.payload else "",
            "page_number": point.payload.get("page_number") if point.payload else None,
            "id": str(point.id),
        }
        for point in all_points
    ]
    sparse_index = SparseVectorIndex()
    sparse_index.fit(documents)
    return sparse_index

def sparse_search(
    query_text: str, top_k: int = 5, collection: str | None = None
) -> list[RetrievedChunk]:
    """Pure sparse search using TF-IDF (no dense embeddings, no fusion)."""
    sparse_index = _build_sparse_index(collection)
    return sparse_index.search(query_text, top_k=top_k)


def hybrid_search(
    query_embedding: list[float],
    query_text: str,
    top_k: int = 5,
    rrf_k: int = 60,
    sparse_top_k: int = 20,
    collection: str | None = None,
) -> list[RetrievedChunk]:

    from app.services.sparse_vector_service import fuse_rrf
    dense_results = search(query_embedding, top_k=sparse_top_k, collection=collection)
    sparse_index = _build_sparse_index(collection)
    sparse_results = sparse_index.search(query_text, top_k=sparse_top_k)
    fused = fuse_rrf([dense_results, sparse_results], rrf_k=rrf_k)
    return fused[:top_k]
