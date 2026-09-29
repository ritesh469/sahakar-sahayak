import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.security.injection_patterns import find_injection


def _validate_user_text(v: str, field: str) -> str:
    """Shared by ChatRequest and QueryRequest: non-empty, has letters, no injection phrase
    (English, Hindi, Hinglish, Marathi patterns in app/security/injection_patterns.py)."""
    v = v.strip()
    if not v:
        raise ValueError(f"{field} cannot be empty or whitespace only")
    if find_injection(v):
        raise ValueError(f"{field} contains potentially malicious content")
    if re.match(r"^[\W_]+$", v):
        raise ValueError(f"{field} must contain actual text content")
    return v


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User message to the AI assistant",
    )
    @field_validator("message")
    @classmethod
    def validate_message_content(cls, v: str) -> str:
        return _validate_user_text(v, "Message")


class RetrievedChunkPreview(BaseModel):
    text: str
    source: str
    score: float = 0.0
    page_number: int | None = None

class ResponseMetadata(BaseModel):
    route: str = "rag"
    retrieved_chunks: list[RetrievedChunkPreview] = Field(default_factory=list)
    cache_hit: bool = False
    reflection_iterations: int = 0
    reflection_score: float | None = None
    refined_question: str | None = None


class PendingSQLBlock(BaseModel):
    sql: str
    query_id: str
    explanation: str = ""


class ChatResponse(BaseModel):
    answer: str = Field(..., min_length=0)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    pending_sql: PendingSQLBlock | None = None
    cache_hit: bool = False
    cost_saved: str = "$0.00"
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


class QueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User question",
    )
    enable_rerank: bool = False
    top_k: int = Field(default=5, ge=1, le=50)
    enable_hyde: bool = False
    # dense | bm25 | tfidf | hybrid (dense + BM25 via RRF); default = SEARCH_MODE (P8)
    search_mode: Literal["dense", "bm25", "tfidf", "hybrid"] = Field(
        default_factory=lambda: settings.search_mode
    )
    enable_crag: bool = Field(default_factory=lambda: settings.crag_enabled_by_default)
    enable_self_reflective: bool = False

    @field_validator("question")
    @classmethod
    def validate_question_content(cls, v: str) -> str:
        return _validate_user_text(v, "Question")


class RetrievedChunk(BaseModel):
    text: str
    source: str
    score: float = 0.0
    page_number: int | None = None

class CRAGEvaluation(BaseModel):
    relevance_score: float = 0.0
    relevance_label: str = "" 
    confidence: float = 0.0
    reasoning: str = ""

class ReflectionResult(BaseModel):
    """Self-RAG reflection on a generated answer."""

    reflection_score: float = 0.0
    needs_regeneration: bool = False
    refined_question: str = ""
    reasoning: str = ""
