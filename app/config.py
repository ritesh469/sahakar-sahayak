from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: str = ""
    groq_api_key: str = ""
    # Chat LLM: "groq" (OpenAI-compatible API) or "openai"
    llm_provider: str = "groq"
    llm_model_answer: str = "openai/gpt-oss-120b"
    # Grader (CRAG, Self-RAG, Ragas) on a different model: Groq limits are per model
    llm_model_grader: str = "qwen/qwen3.8-27b"
    llm_reasoning_effort: str = "low"  # gpt-oss only; "" = provider default
    llm_max_retries: int = 6  # SDK retries with backoff on 429 / 5xx

    # Text2SQL is a leftover of the K8s project: off = no LLM router, every query is RAG
    # (also hides the Streamlit SQL approval tab)
    sql_enabled: bool = False
    # Streamlit upload tab (the API has no upload endpoint; ingest with scripts/seed_db.py)
    ui_upload_enabled: bool = False

    # Embeddings: "local" = sentence-transformers on GPU/CPU, "openai" = OpenAI API
    embedding_backend: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # Chunking (tokens are counted with the embedding model's tokenizer)
    chunk_size: int = 512
    chunk_overlap: int = 0
    # PDF text backend: "pypdfium2" or "docling_parse" (docling default; drops pages with
    # std::bad_alloc on this Windows machine)
    pdf_backend: str = "pypdfium2"
    # Cache of converted documents (docling JSON); "" disables the cache
    doc_cache_dir: str = "data/cache/docling"

    qdrant_url: str = "http://localhost:6333"
    # Collection name = f"{prefix}_{chunk_size}", one collection per chunk size
    qdrant_collection_prefix: str = "coop"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/adv_rag"

    # Host ports used by docker-compose.yml (declared here so .env validation passes)
    postgres_host_port: int = 5432
    qdrant_host_port: int = 6333
    qdrant_grpc_host_port: int = 6334
    api_host_port: int = 8000

    upstash_redis_url: str = ""
    upstash_redis_token: str = ""
    cache_ttl_embeddings: int = 604_800
    cache_ttl_rag: int = 3_600
    cache_ttl_sql_gen: int = 86_400
    cache_ttl_sql_result: int = 900
    cache_ttl_intent: int = 86_400

    storage_backend: str = "local"
    s3_cache_bucket: str = "adv-rag-cache"
    aws_region: str = "us-east-1"

    tavily_api_key: str = ""


    jwt_secret: str = ""
    jwt_expiration_minutes: int = 60

    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60
    max_tokens_per_user_daily: int = 100_000
    auth_login_rate_limit_per_min: int = 5
    auth_register_rate_limit_per_hour: int = 3

    max_input_tokens: int = 3_000
    reserved_context_tokens: int = 1_000
    reserved_output_tokens: int = 1_000

    prompt_injection_threshold: float = 0.75
    toxicity_threshold: float = 0.75
    output_toxicity_threshold: float = 0.5
    max_validation_retries: int = 2

    hyde_num_hypotheses: int = 3
    hyde_enabled_by_default: bool = False
    hybrid_search_enabled: bool = True
    rrf_k: int = 60
    reranker_backend: str = "local"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    voyage_api_key: str = ""
    voyage_model: str = "rerank-2.5"
    reranker_initial_top_k: int = 20
    reranking_enabled_by_default: bool = True
    crag_relevance_threshold: float = 0.7
    crag_ambiguous_threshold: float = 0.5
    crag_enabled_by_default: bool = False
    # CRAG may replace bad retrieval with Tavily web results; off = answers only from our documents
    web_fallback_enabled: bool = False
    reflection_min_score: float = 0.85
    max_reflection_retries: int = 2
    self_reflective_enabled_by_default: bool = False


    vanna_model: str = "gpt-4o"
    vanna_temperature: float = 0.0
    vanna_seed: int = 42

    log_json: bool = False
    log_level: str = "INFO"



settings = Settings()




    



    


