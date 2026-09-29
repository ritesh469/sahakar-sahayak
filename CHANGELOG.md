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

- `/auth/login` 500 deta hai: rate limiter ko Upstash Redis chahiye (CLAUDE.md Setup problem S2).
- Groq chat + local embeddings: P2 (EMBEDDING_DIM) / P5 (model names).
