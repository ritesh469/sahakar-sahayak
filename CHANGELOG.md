# Changelog

Har step (P1, P2, …) ki entry yahan likhi jaati hai: kya badla, kyun, aur kaise verify kiya.

---

## P1 — Project chalu karna (2026-09-29)

**Kya hua (simple Hinglish mein):** Project ko Windows par chala diya. Database, vector DB aur FastAPI
teeno chal rahe hain, aur `/admin/health` jawab de raha hai. Koi feature change nahi kiya, sirf setup
ki dikkatein theek ki.

### Setup (Windows commands)

```powershell
# 1) Dependencies (Python 3.12, CUDA torch)
uv python pin 3.12
uv sync --extra dev

# 2) Postgres + Qdrant (ports .env se: 5434 / 6335 / 6336)
docker compose up -d postgres qdrant

# 3) Sirf migration 001 + demo users (003 K8s SQL skip)
uv run --env-file .env python -c "import os, psycopg2; from scripts.seed_db import seed_users, MIGRATIONS_DIR; c = psycopg2.connect(os.environ['DATABASE_URL']); cur = c.cursor(); cur.execute(open(os.path.join(MIGRATIONS_DIR, '001_create_users.sql'), encoding='utf-8').read()); c.commit(); seed_users(c); c.close()"

# 4) API start + health check
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
curl http://127.0.0.1:8001/admin/health
```

### Errors aur unke root cause / fix

| # | Error | Root cause | Fix |
|---|-------|-----------|-----|
| 1 | `.venv` OneDrive mein sync hota | Project `OneDrive\Desktop` mein tha | Project `C:\Projects\EnterpriseRAG` mein copy kiya |
| 2 | `failed to hardlink ... os error 396` | uv cache se hardlink Windows par fail | `pyproject.toml` → `[tool.uv] link-mode = "copy"` |
| 3 | `No module named 'jsonpatch'` | Error 2 ki wajah se `jsonpatch` adhoora install hua (dist-info bina RECORD) | Broken folder hata ke dobara install |
| 4 | `port is already allocated` (5432) | `retail-fde-project` ke containers 5432/6333/8000 par | Ports `.env` se configurable; is project ke liye 5434 / 6335 / 6336 / 8001 |
| 5 | (chhupa hua) port 5433 par native Windows Postgres | `localhost:5433` galat DB par jaata | Postgres 5434 par shift |
| 6 | `Extra inputs are not permitted` | `Settings` strict hai; naye port vars class mein nahi the | `app/config.py` mein 4 port fields add |
| 7 | `psycopg ... libpq library not found` | psycopg3 ko libpq chahiye, Windows par nahi hoti | `psycopg[binary]` dependency add |
| 8 | `OpenAIError: Missing credentials` | Naya openai SDK khaali key par import time crash | `.env` mein placeholder key (Groq support P2/P5 mein) |

### Files badle

- `pyproject.toml`: CUDA 12.6 torch/torchvision index, `link-mode = "copy"`, `psycopg[binary]`.
- `uv.lock`: upar ke hisaab se regenerate.
- `docker-compose.yml`: host ports `${POSTGRES_HOST_PORT:-5432}` jaise env vars se.
- `.env.example`: "Host ports" section add.
- `app/config.py`: `postgres_host_port`, `qdrant_host_port`, `qdrant_grpc_host_port`, `api_host_port`.
- `.gitattributes`: PDF/DOCX binary mark (line-ending corruption se bachao).
- `CLAUDE.md`: prompts + environment notes + Known problems DRAFT.

### Verify kiya

- `torch 2.12.1+cu126`, `cuda.is_available() = True` (RTX 4060).
- Postgres: sirf `users` table; demo users `agent@demo.local` (admin=False), `admin@demo.local` (admin=True).
- `/admin/health` →
  `{"status":"degraded","qdrant":true,"postgres":true,"redis":false,"openai":false,"tavily":true}`
  - `redis:false` → Upstash configure nahi (expected).
  - `openai:false` → placeholder key (expected; Groq baad mein).

### Abhi khula (next steps)

- Groq chat + local embeddings: P2 (EMBEDDING_DIM) / P5 (model names).

---

## P1 follow-up — Redis ke bina login (2026-09-29)

**Kya hua:** `/auth/login` 500 deta tha, kyunki rate limiter aur token budget ko Upstash Redis (cloud)
chahiye tha. Ab Upstash configure na ho to dono memory mein count karte hain (query cache jaisa).
Upstash `.env` mein daaloge to purana Redis wala raasta hi chalega.

- `app/middleware/rate_limiter.py`: sliding-window in-memory fallback (same semantics as Redis ZSET).
- `app/security/token_budget.py`: per-user per-day in-memory counter fallback.
- `tests/test_redis_fallback.py`: 4 tests (limit, alag keys, window expiry, budget) — **4 passed**.
- Live check (port 8001): agent login → token; galat password → 401; admin `/admin/cache/stats` → 200;
  1 minute mein 6th login → 429 `Rate limit exceeded`.
- Limitation: memory counter sirf ek process ke andar hai (uvicorn multiple workers mein share nahi hoga).

---

## P2 — Config, chunking, page number, local embeddings (2026-09-29)

**Kya hua (simple Hinglish mein):** Chunk size, overlap aur embedding dimension ab `.env` se aate hain.
Embeddings ab GPU par local model (`BAAI/bge-m3`) se bante hain, kyunki Groq embeddings nahi deta.
Har chunk ke saath `page_number` ab Qdrant tak jaata hai aur search results mein wapas aata hai.
Har chunk size ki apni Qdrant collection hai (`coop_256`, `coop_512`, `coop_1024`), taaki experiments
ek dusre ko overwrite na karein. Known problems #3, #4, #5, #6 fix.

### Naye `.env` settings

| Setting | Value | Kyun |
|---|---|---|
| `EMBEDDING_BACKEND` | `local` | `local` (sentence-transformers) ya `openai` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | multilingual (Hindi/Marathi), 8192 tokens, P5 ke `bge-reranker-v2-m3` ka jodidaar |
| `EMBEDDING_DIM` | `1024` | pehle `VECTOR_SIZE = 1536` hardcoded tha |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `512` / `0` | tokens bge-m3 tokenizer se gine jaate hain |
| `PDF_BACKEND` | `pypdfium2` | docling-parse pages gira raha tha (neeche error 3) |
| `QDRANT_COLLECTION_PREFIX` | `coop` | `QDRANT_COLLECTION` ki jagah |

### Files badle

- `app/config.py`, `.env.example`, `.env`: upar wale settings.
- `app/services/document_processor.py`:
  - device `MPS` → `AUTO` (CUDA);
  - `HybridChunker` ka tokenizer = embedding model ka tokenizer, max tokens = `CHUNK_SIZE`;
  - `CHUNK_OVERLAP` khud implement kiya (HybridChunker mein option nahi hai): chunk `size - overlap`
    tak, phir pichhle chunk ke aakhri `overlap` tokens aage jode;
  - `page_number` = jis page par chunk shuru hota hai (multi-page paragraph ke liye `charspan` se);
  - `PDF_BACKEND` option; conversion `PARTIAL_SUCCESS` ho to missing pages ka WARNING.
- `app/services/embedding_service.py`: local sentence-transformers backend (CUDA fp16, normalized, ek hi
  baar load, dim check). OpenAI client ab lazy (sirf `openai` backend par).
- `app/services/query_cache_service.py`: embedding cache key mein model ka naam.
- `app/models.py`: `RetrievedChunk` aur `RetrievedChunkPreview` mein `page_number: int | None`.
- `app/services/vector_store.py`: `collection_name(chunk_size)`, har function mein optional
  `collection=`, `EMBEDDING_DIM` se collection, size mismatch par error, `recreate_collection()`,
  deterministic point id (`uuid5(source, page, text)`) → dobara ingest par duplicate nahi.
- `sparse_vector_service.py` (`fuse_rrf`, TF-IDF), `reranking.py`, `rag_service.py`: `page_number` aage pass.
- `scripts/seed_db.py`: `--chunk-size`, `--recreate`, `--ingest-only` (Postgres/migrations skip; S1 se bachao).
- `pyproject.toml`: pytest `pythonpath = ["."]` (tests `scripts.*` import kar sakein).
- `tests/test_page_number.py`: 7 naye tests.
- `CLAUDE.md`: #3–#6 FIXED, environment notes, naye setup problems S7, S8.

### Errors aur unke root cause / fix

| # | Error | Root cause | Fix |
|---|-------|-----------|-----|
| 1 | `OSError: [WinError 1314] A required privilege is not held` (docling model download) | Windows Developer Mode off → symlink ki permission nahi; HF `snapshot_download` 8 threads mein chalta hai aur symlink-check mein race hai, isliye kuch threads symlink try kar lete hain | Docling models ek thread (`max_workers=1`) se download kiye (CLAUDE.md S7) |
| 2 | Saare chunks "p. 1" (30 chunks, sirf 5 pages) | Docling ne ek lamba paragraph (pages 1–7) ek hi item banaya; chunker ke har tukde ko poori page-list mili aur `min()` = 1 | `prov.charspan` se chunk ki shuruaat wala page (pypdf se 3 chunks cross-check: p. 2, 3, 5 sahi) |
| 3 | `Stage preprocess failed ... std::bad_alloc`, pages gaayab | docling-parse backend kuch pages par crash karta hai (har run alag pages; 15–16 hamesha), aur docling chup-chaap `PARTIAL_SUCCESS` deta hai | `PDF_BACKEND=pypdfium2`: 16/16 pages, zyada text, ~2x tez. Missing pages ab log hote hain |

### Verify kiya

- `pytest tests/` → **11 passed** (7 naye + 4 purane):
  - 2-page PDF (reportlab) → har chunk mein `page_number`, pages {1, 2}, text sahi page par;
  - multi-page paragraph → sahi page (fake objects);
  - chunk ≤ `CHUNK_SIZE` tokens; overlap = pichhle chunk ki tail;
  - collection naam `coop_<size>`;
  - `seed_db._ingest_one` → temporary Qdrant collection → payload aur search dono mein page {1, 2};
    dobara ingest par points ki ginti same (duplicate nahi).
- Manual end-to-end (asli bge-m3, temporary collection, baad mein delete):
  - Hindi sentence → 1024-dim, norm 1.0, CUDA;
  - K8s PV PDF (16 pages) → 32 chunks, tokens min/avg/max = 62/388/498 (≤ 512), pages 1–15;
  - query "reclaim policy" → top result `persistent-volumes.pdf, p. 2` (pypdf se confirm).
- `/admin/health` → `qdrant:true, postgres:true` (redis/openai false: expected, P1 jaisa).

### Abhi khula (next steps)

- Asli Hindi/Marathi PDFs par `pypdfium2` vs `docling_parse` text quality P3 (`check_docs.py`) mein dekhna.
- `_ingest_one` fail hone par sirf exception type log karta hai → P4 report ke liye message bhi chahiye.
- Sparse index cache aur `scroll(limit=10000)` → P8.
