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

---

## P3 — Documents check (2026-09-29)

**Kya hua (simple Hinglish mein):** Purane Kubernetes documents `seed/docs/_k8s_backup/` mein move kiye
(delete nahi, `git mv`). Naye documents check karne ke liye `scripts/check_docs.py` bana, aur
`data/sources.csv` ka template bana. **Abhi `true_data/` khaali hai** (naye documents daalne baaki hain),
isliye `sources.csv` mein sirf header hai.

### Files

- `seed/docs/true_data/*` → `seed/docs/_k8s_backup/` (47 files: 12 pdf, 12 docx, 12 html, 11 txt; sab K8s).
- `scripts/check_docs.py` (naya): har document ke liye
  - naam, pages (PDF; baaki formats `-`), characters;
  - language guess: Devanagari % (≥60% → hi/mr, ≤10% → en, beech mein mixed);
    hi vs mr aam shabdon se (है/और/में vs आहे/आणि/नाही, aur ळ);
  - pehle 400 characters, **usi docling converter se jo ingestion use karta hai**;
  - `SUSPICIOUS` agar: text < 200 chars, PDF mein < 100 chars/page (scan?), letters < 50%,
    ajeeb symbols > 2% (U+FFFD, private-use, control, `(cid:`), legacy Hindi font (Kruti Dev jaisa:
    `ds`, `esa`, `gS` jaise tokens ≥ 3%), ya conversion mein pages gaayab/fail.
  - `--write-sources`: `data/sources.csv` mein naye filenames jodta hai; aapki bhari rows nahi badalta.
  - `--pdf-backend docling_parse`: extraction compare karne ke liye; `--dir`, `--limit`.
- `data/sources.csv` (naya): `filename,title,source_url,download_date,language,category`
  (UTF-8 BOM, taaki Excel mein Hindi/Marathi sahi dikhe).
- `scripts/seed_db.py`: `seed/docs/README.md` ab corpus mein ingest nahi hota (pehle top-level `.md`
  "legacy doc" maan ke ingest ho jaata tha).
- `tests/test_check_docs.py` (naya): 10 tests.

### Verify kiya

- `pytest tests/` → **21 passed** (10 naye).
  - Hand-made samples: Hindi → `hi`, Marathi → `mr`, English → `en`, Hindi+English → `mixed`;
    Kruti Dev text, khaali scan, kam text per page, ajeeb symbols, sirf symbols → SUSPICIOUS;
    `sources.csv` sync bhari rows ko nahi chhoota.
- `check_docs.py --dir seed/docs/_k8s_backup` (47 asli files) → sab `en`, **SUSPICIOUS 0**
  (saaf English docs par koi false alarm nahi).
- Docling `.txt` ko Markdown ki tarah padhta hai (ingestion mein chalega).

### Abhi khula (next steps)

- **Naye documents `seed/docs/true_data/` mein daalo**, phir:
  `uv run --env-file .env python scripts/check_docs.py --write-sources`
  SUSPICIOUS files khud dekho, kharab hatao, aur `sources.csv` mein title/URL/date/language/category bharo.
- Hindi/Marathi heuristics abhi sirf hand-made samples par test hue hain; asli docs par output dekh ke
  thresholds adjust karne pad sakte hain.
- Scanned Hindi/Marathi PDFs ke liye OCR support nahi (RapidOCR = Chinese/English).

---

## P3 (poora) — 23 official documents + text quality check (2026-09-29)

**Kya hua (simple Hinglish mein):** Claude ne official sarkari sites se documents dhoondh ke (list
dikha ke, user ki manzoori ke baad) 25 PDFs download kiye. `check_docs.py` se sab check kiye:
2 scanned Marathi PDFs kharab nikle (hataye), 1 bahut bada GR kaata. Ab corpus mein **23 documents**
hain. Badi finding: **har Hindi/Marathi PDF ka text layer kuch had tak toota hua hai** (PDF fonts
galat Unicode dete hain) — ye paper mein limitation/finding ke roop mein jaayega.

### Corpus (`seed/docs/true_data/`, details `data/sources.csv` mein)

| Language (sources.csv) | Documents | Sources |
|---|---|---|
| en | 9 | cooperation.gov.in, pmkisan.gov.in, krishi.maharashtra.gov.in |
| mr | 7 | krishi.maharashtra.gov.in, sahakarayukta.maharashtra.gov.in, pmkisan.gov.in |
| hi | 4 | cooperation.gov.in, pmkisan.gov.in |
| en+hi (bilingual) | 3 | cooperation.gov.in (MSCS Rules), pmkisan.gov.in (PM-KMY) |

Categories: government-scheme 13, cooperative-scheme 4, cooperative-policy 3, cooperative-law 3.
Parallel versions (paper mein language comparison ke liye): National Cooperation Policy (en/hi),
Grain Storage Plan SOP (en/hi), PM-KISAN e-KYC note (en/hi/mr), Women Farmers Act (en/mr).

### Faisle (decisions)

| Faisla | Kyun |
|---|---|
| 3 badi booklets download nahi ki (Gram Panchayat guide en/hi, Coop-among-Coops SOP; 89 MB) | zyaadatar images, user ne 25 files chuni |
| RBI KCC circular aur Gopinath Munde guidelines chhode | link HTML/404 de raha tha |
| `mh_coop_election_panel_guidelines_mr.pdf`, `mh_coop_policy_press_note_mr.pdf` → `seed/docs/_excluded/` | scanned; RapidOCR (Chinese/English) Marathi ko Chinese akshar bana deta hai |
| `mh_pmfby_gr_2026_mr.pdf` sirf pages 1–52 (GR text + forms) | pp. 53–481 zila-war tables (corpus ka ~43% ho jaata); original `seed/docs/_originals/` (gitignored); page numbers wahi rahe |

### Code

- `scripts/check_docs.py`: naye checks —
  - **unexpected script**: 5% se zyada letters na Devanagari na Latin (OCR se Chinese akshar) → SUSPICIOUS;
  - **expected language**: `sources.csv` hi/mr kahe par text Devanagari na ho → SUSPICIOUS;
  - **damaged Devanagari text layer** (WARN, SUSPICIOUS nahi): shabd jo matra se shuru hon ya jisme
    do matra lagataar hon (`भारि` = भारत, `मकया` = किया) — asli Hindi/Marathi mein aisa nahi hota;
  - ab usi `DocumentProcessor.convert()` + disk cache se chalta hai jo ingestion use karta hai
    (conversion ek hi baar); progress turant print (line buffering).
- `app/services/text_cleaning.py` (naya): "fake bold" PDFs mein dohraai gayi matra/anusvara ek karna
  (`महाारााष्ट्र` → `महाराष्ट्र`). Women Farmers Act (mr) ke toote shabd 70% → 15%.
- `app/services/document_processor.py`: `convert()` + docling JSON cache (`DOC_CACHE_DIR`,
  default `data/cache/docling`, gitignored); chunk text par `clean_extracted_text`.
- `app/config.py`, `.env.example`: `DOC_CACHE_DIR` (saath mein aage ke steps ke settings bhi).

### Text layer quality (check_docs, cleaning ke baad: malformed Devanagari words)

| Document | Broken | Document | Broken |
|---|---|---|---|
| grain_storage_plan_sop_hi | 13% | ncp_2025_hi | 22% |
| mh_agri_citizen_charter_schemes_2026_mr | 20% | pmkisan_ekyc_note_hi | 35% |
| mh_farmer_loan_waiver_2026_mr | 10% | pmkisan_ekyc_note_mr | 12% |
| mh_fruit_crop_insurance_gr_2026_mr | 18% | pmkisan_hi | 27% |
| mh_pkvy_gr_mr | 10% | mh_pmfby_gr_2026_mr | 24% |
| mh_women_farmer_act_2026_mr | 15% | mscs_amendment_rules_2023 (en+hi) | 10% |

pypdfium2, pypdf aur docling_parse — teeno se same toota text aata hai (grain_storage_plan_sop_hi
p. 6 par check kiya), yaani problem PDF ke andar ki hai, backend ki nahi.

### Verify kiya

- `pytest tests/test_check_docs.py` → 13 passed (OCR Chinese garbage, expected-language mismatch,
  damaged Devanagari = WARN, clean Hindi/Marathi = 0%).
- `check_docs.py` final run: **23 files | SUSPICIOUS: 0 | WARN: 16** (sirf Devanagari text-layer warnings).

---

## P4 — Ingestion, chunk size 512 (2026-09-29)

**Kya hua:** Saare 23 documents `coop_512` collection mein ingest hue (noise sample 0). Report
`results/ingestion_512.json` mein hai (per-document aur language-wise numbers ke saath).

| Metric | Value |
|---|---|
| Documents ingested / failed | 23 / 0 |
| Pages (total / missing) | 673 / 0 |
| Chunks | 1,969 (sab ke saath page_number) |
| Avg chunk length | 875.7 characters, 333.8 tokens (bge-m3 tokenizer) |
| Min / max chunk tokens | 5 / 512 |
| Chunks by language (sources.csv) | en 433, hi 209, mr 1,023, en+hi 304 |
| Time | 1.3 min (conversion cache se; bina cache ~35 min) |

Sabse zyaada chunks: `mh_fruit_crop_insurance_gr_2026_mr.pdf` (669, zila-war tables),
`mscs_act_2002_en.pdf` (174), `mh_pmfby_gr_2026_mr.pdf` (169).

### Files

- `scripts/seed_db.py`: `--report PATH` → JSON (documents, chunks, avg chars/tokens, min/max,
  pages, missing pages, language-wise, har failure ki poori wajah, per-document record).
  `_ingest_one` ab exception ka message bhi log karta hai (pehle sirf type).
- `app/services/document_processor.py`: 10 se kam non-space characters wale chunks index nahi hote
  (pehle 19 aise the: `''`, `'1643145)'`, `'000\n.'` — image placeholders / table ke tukde).
- `tests/test_page_number.py`: conversion cache temp folder mein; ingestion record aur cache-hit check;
  koi khaali chunk nahi.

### Verify kiya

- `pytest tests/` → **50 passed**.
- Qdrant `coop_512`: 1,969 points, sab ke payload mein `page_number`.

---

## P5 — Domain, grounding, multilingual answer (2026-09-29)

**Kya hua (simple Hinglish mein):** Chatbot ab K8s SRE assistant nahi, **"Sahakar Sahayak"** hai: sirf
documents se jawab deta hai, sawaal ki language mein jawab deta hai, har fact ke baad `[file, p. N]`
citation lagata hai, jawab na mile to ek fixed "nahi mila" sentence bolta hai, aur domain ke bahar ke
sawaal (cricket, film) par politely mana karta hai. Chat LLM ab Groq par hai. Known problems #7, #8,
#9, #10, #13 aur setup problems S3, S5 fix.

### Kya badla (file by file)

| File | Badlav | Kyun |
|---|---|---|
| `app/security/system_prompt.py` | Naya prompt: language, grounding, citation, refusal, out-of-domain, security, plain text. Refusal/OOD sentences 4 languages mein constants (`REFUSAL_MESSAGES`, `OUT_OF_DOMAIN_MESSAGES`) | Eval (P11) exact sentence dhoondh ke refusal/hallucination ginta hai |
| `app/services/language.py` (naya) | Rule-based detector: Devanagari % + Hindi/Marathi aam shabd (है/आहे, ळ, -ांना) + Hinglish shabd (kya, kaise, mein) → en/hi/mr/hinglish | LLM Hinglish sawaal ka jawab Devanagari mein de deta tha; ab prompt mein `Answer language:` jaata hai |
| `app/services/rag_service.py` | `_route()`: SQL off → seedha "rag" (LLM router call nahi); `run_rag(intent=...)`; `retrieve()` public; `【】` citation → `[]` | Har query par 2 extra LLM calls bachi |
| `app/core/graph.py` | `route_intent` SQL off par skip; `generate_answer` intent aage deta hai (dobara routing nahi); `retrieve_rag` asli chunks | Double routing + source-string-as-text bug |
| `app/security/spotlighting.py` | `<chunk source=".." page="N">` | LLM ko page pata ho tabhi `p. N` cite kar sakta hai |
| `app/services/crag.py` | `WEB_FALLBACK_ENABLED=false` par web search nahi; relevance "incorrect" → chunks hata do (→ refusal) | Documents ke bahar ka content answer mein na aaye |
| `app/models.py` | `enable_crag` default = `CRAG_ENABLED_BY_DEFAULT` (false) | |
| `app/services/llm_service.py` | `get_client()` lazy; Groq base_url; `max_retries` (429); gpt-oss ke liye `reasoning_effort=low` | S3; Groq free tier tokens/min limit |
| `app/services/reranking.py` | CrossEncoder ek baar load, cache (fp16 CUDA, `max_length=1280`) | S5: har query par ~2 GB model load |
| `app/api/admin.py` | `/admin/health`: `llm` + `llm_provider`; redis/tavily band hon to `null` (status degrade nahi) | |
| `app/__init__.py` | Windows par `pyarrow.dataset` pehle import | Naya crash S9 (neeche) |
| `tests/test_grounding.py` (naya) | 5 tests | |
| `tests/test_language.py` (naya) | 12 tests (EN/HI/MR/Hinglish detection) | |

### Error aur root cause

| Error | Root cause | Fix |
|---|---|---|
| Pehli test query par Python bina error message ke band (`Segmentation fault`, exit 139) | Windows DLL conflict: `grpc` (Qdrant client) + `psycopg2` (SQL service) + `torch` pehle load, phir `pyarrow.dataset` (sentence_transformers → datasets → pandas) load hote hi access violation. Imports ek-ek karke hata ke (bisect) minimal repro mila: `python -c "import grpc, psycopg2, torch, pyarrow.dataset"` | `app/__init__.py` mein Windows par `pyarrow.dataset` sabse pehle load (CLAUDE.md S9) |

### Test query (dense + rerank, top 5, `coop_512`, `openai/gpt-oss-120b` on Groq)

| Sawaal | Jawab (chhota) | Top source |
|---|---|---|
| EN: PM-KISAN mein saal ke kitne paise, kitni kiston mein? | Rs 6,000/year, 3 kist Rs 2,000 `[pmkisan_ekyc_note_en.pdf, p. 1]` | pmkisan_ekyc_note_en p. 1 |
| HI: पीएम-किसान योजना में साल में कितनी राशि? | हिंदी में: ₹6,000, तीन किस्तें `[… p. 1]` | pmkisan_ekyc_note_en p. 1 |
| MR: पीएम किसान ई-केवायसी कशी करावी? | मराठी में: 3 modes + steps, har line citation | pmkisan_ekyc_note_en p. 2 |
| Hinglish: PM-KISAN ka e-KYC kaise karein? | Hinglish (Latin script) mein: OTP / biometric / face auth | pmkisan_ekyc_note_hi p. 1 |
| Unanswerable: Bihar mein 2024 mein kitni societies register hui? | "I could not find this information in the available documents." | (rerank score 0.08) |
| Out-of-domain: 2011 cricket world cup? | "This assistant only answers questions about cooperatives and government schemes." | – |

Latency: pehla sawaal 30.7 s (bge-m3 + reranker load), baaki 1.7–2.4 s; unanswerable/OOD ~23 s
(shayad Groq tokens/min limit par SDK ka retry-wait; P7 mein naapenge).

### Verify kiya

- `pytest tests/` → **55 passed**.
- Upar ke 6 sawaal: sahi language, citation, refusal aur OOD sentence.

### Abhi khula

- Marathi jawab mein LLM ne `**bold**` heading lagayi (prompt "plain text" kehta hai); Streamlit mein theek
  dikhta hai, eval par asar nahi.
- Hindi sawaal ka citation English document ka hai (dono retrieve hue the) — galat nahi, par
  language-wise analysis (P13) mein dekhna.

---

## P6 — Streamlit UI cleanup (2026-09-30)

**Kya hua (simple Hinglish mein):** Streamlit app ab "Sahakar Sahayak — Cooperative & Scheme Assistant"
hai. K8s wale hisse hate, SQL approval aur upload tab chhup gaye, sidebar mein 4 bhashaon ke example
sawaal hain, aur jawab ke neeche sources "filename, p. N" format mein aate hain.

### Kya badla

| File | Badlav |
|---|---|
| `scripts/streamlit_app.py` | Title/branding; SQL approval tab sirf `SQL_ENABLED=true` par, upload tab sirf `UI_UPLOAD_ENABLED=true` par (API mein upload endpoint hi nahi hai); search mode dropdown ke options API schema (`/openapi.json`) se aate hain, isliye P8 ke baad `bm25`/`tfidf` apne aap dikhenge; sources "filename, p. N" (`_format_source`); sidebar mein EN/HI/MR/Hinglish example sawaal (Claude ne corpus se chune; badalne ho to `EXAMPLE_QUESTIONS`); "Current Lesson: lesson-9" banner (purane course ka) hataya; login form mein `seed_db.py` ka demo agent pehle se bhara (pehle galat password tha → 401) |
| `app/core/state.py` | `GraphState` mein `metadata` key. LangGraph undeclared keys chhod deta hai, isliye `/query` ka `metadata.retrieved_chunks` hamesha khaali aata tha aur UI mein page number kabhi nahi dikhta tha |

### Verify kiya

- Browser (in-app preview, port 8502 + API 8001): title/branding, 4 tabs (Auth, Query, History,
  Evaluation Results; SQL/upload chhupe), sidebar examples, demo login → `200 OK`, example button
  sawaal ko question box mein daalta hai, search mode dropdown.
- API `/query` (login + guardrails) Marathi sawaal → Marathi jawab + 5 chunks page ke saath
  (`mh_women_farmer_act_2026_mr.pdf, p. 9` …). UI mein answer card ka aakhri render browser pane
  band hone ki wajah se screenshot se confirm nahi hua; format function `_format_source` wahi hai.
- Pehli API query par llm-guard ~3 GB models download karta hai aur spaCy packages venv mein install
  karta hai (CLAUDE.md S10) — pehli query 10+ minute le sakti hai.

---

## P7 — Din 1 gate: smoke test (2026-09-30)

**Kya hua (simple Hinglish mein):** `scripts/smoke_test.py` bana. Ye 10 sawaal (2 EN, 2 HI, 2 MR,
2 Hinglish, 1 unanswerable, 1 out-of-domain) seedha `rag_service` se chalata hai aur har sawaal ka
jawab, sources (page ke saath), latency (retrieval + generation alag) print karta hai, aur check karta
hai ki (a) sahi document top-5 mein aaya, (b) jawab sawaal ki language mein hai, (c) unanswerable/OOD
par sahi fixed sentence aaya. Result `results/smoke_test.json` mein. Is test ne 3 bug pakde (neeche).

Sawaal Claude ne documents padh ke chune (har expected answer chunk text mein dekha):
surcharge 12%→7% (`coop_income_tax_benefits.pdf` p. 1), PM-KMY ₹3000/maah 60 saal ke baad
(`pmkmy_faqs_en.pdf` p. 1), NCP 2025 "50 करोड़ लोग" (`ncp_2025_hi.pdf` p. 25 / en p. 23), अन्न भंडारण
PACS infrastructure (`grain_storage_plan_sop_*`), कर्जमुक्ती ₹2 लाख (`mh_farmer_loan_waiver_2026_mr.pdf`
p. 1/3), राज्य संनियंत्रण समिती अध्यक्ष = मुख्य सचिव (`mh_women_farmer_act_2026_*`), NCDC sugar mills
₹1000 Cr (`ncdc_sugar_mills_scheme.pdf` p. 1), PM-KISAN e-KYC modes.

### Result (dense + rerank, top 5, `coop_512`, gpt-oss-120b)

| id | lang | answer lang | sahi doc rank | refusal | total s | |
|---|---|---|---|---|---|---|
| en1 | en | en | 1 | – | 43.7 (pehli query, model load) | OK |
| en2 | en | en | 1 | – | 2.7 | OK |
| hi1 | hi | hi | 1 (sirf English NCP) | – | 2.6 | OK |
| hi2 | hi | hi | 1 | – | 2.6 | OK* |
| mr1 | mr | mr | 1 | – | 25.2 | OK |
| mr2 | mr | mr | 1 | – | 19.5 | OK |
| hinglish1 | hinglish | hinglish | 1 | – | 25.3 | OK |
| hinglish2 | hinglish | hinglish | 1 | – | 12.1 | OK |
| unans1 | en | en | – | no_info | 26.7 | OK |
| ood1 | hinglish | hinglish | – | out_of_domain | 22.4 | OK |

**Sahi document top-5 mein nahi aaya: kisi mein nahi (10/10).** Par dhyan dene wali baatein:

- *hi2: document sahi mila, par jawab mein "कॉइन-प्रोसेसिंग (coin processing) इकाइयाँ" jaisi galat
  cheez aayi. English SOP mein "common processing units" hai; Hindi PDF ka text layer toota hai
  (`कस्टम हायररंग`, 13% shabd kharab), aur LLM ne toote shabd ka ulta matlab nikaala. Ye
  **hallucination from damaged text layer** hai — paper ki finding.
- hi1: Hindi sawaal par top-5 mein sirf English NCP aaya, Hindi NCP (`ncp_2025_hi.pdf`, 22% toote shabd)
  nahi. bge-m3 cross-lingual kaam karta hai, isliye jawab sahi hai; par Hindi document ka kharab text
  layer uski ranking girata lagta hai (P13 language-wise analysis mein dekhna).
- en1: citation `ncp_2025_en.pdf, p. 12` diya jabki fact `coop_income_tax_benefits.pdf, p. 1` mein hai
  (dono top-5 mein) → citation precision P11 metric mein naapna.
- Latency 2.6 s se 43 s: 20–25 s wale jawab Groq ki 8,000 tokens/min limit par SDK ke retry-wait hain
  (CLAUDE.md "Groq free tier"). Pehli query mein bge-m3 + reranker load (~40 s).

### Is test ne jo bug pakde (aur fix)

| Bug | Root cause | Fix |
|---|---|---|
| English sawaal (PM Kisan Maan-Dhan **Yojana**) ka jawab Hinglish mein | Detector "kisan", "yojana" ko Hinglish shabd ginta tha; ye scheme ke naam hain | `language.py`: yojana/kisan/sahkari Hinglish list se hataye |
| Marathi sawaal (…समितीचे अध्यक्ष कोण असतात?) ka jawab Hindi mein | Koi Marathi pehchaan-shabd nahi mila → default "hi" | Marathi shabd (कोण, असतात, दिली…) + `-ीचे/-ीचा/-च्या` endings; `नीचे` exception |
| Hindi jawab "en" detect | `[mh_…_en.pdf, p. 7]` citation ke Latin letters | Detection se pehle citations hatao |
| **API path par Hindi/Marathi sawaal bigadte** (smoke test mein nahi dikhta, woh API bypass karta hai) | llm-guard PII scanner (English NER) ne "किसान" → `<PERSON><PERSON><PERSON>`, "महिला शेतकरी" → `<PERSON><PERSON><PERSON> <PERSON><PERSON>` kiya — 5 mein se 3 Devanagari sawaal | PERSON entity off (`PII_REDACT_PERSON_NAMES=false`); email/phone ab bhi redact (check kiya) |

### Files

- `scripts/smoke_test.py` (naya), `results/smoke_test.json` (naya).
- `app/services/language.py`, `tests/test_language.py` (+4 regression tests).
- `app/security/content_moderation.py`, `app/config.py`, `.env.example`: PII PERSON flag;
  `tests/test_pii_redaction.py` (naya, 2 tests).
- `eval/metrics.py` + `tests/test_metrics.py` (P11 ke liye pehle se likhe the; smoke test inka
  `refusal_type` use karta hai, isliye isi commit mein).
- `CLAUDE.md`: Known problem #14, S10 (llm-guard downloads), S11 (GPU memory), Groq limits.

### Verify kiya

- `pytest tests/` → sab pass (neeche commit se pehle ka run).
- PII: 11 smoke/example sawaal redaction ke baad bilkul same; `ramesh.patil@example.com` / `9876543210`
  → `<EMAIL_ADDRESS>` / `<PHONE_NUMBER>`.
- API `/query` (guardrails ke saath) Marathi sawaal → sahi Marathi jawab + page wale sources.

---

## P8 — Asli BM25 + Devanagari tokenizer (2026-09-30)

**Kya hua (simple Hinglish mein):** Keyword search (sparse) ab asli **BM25** hai, apne tokenizer ke saath
jo Hindi/Marathi shabdon ko poora rakhta hai. Pehle TF-IDF tha, jiska tokenizer matra (ा ि ी) aur
halant (्) par shabd tod deta tha. BM25 index ab ek hi baar banta hai aur memory mein rehta hai; pehle
har query par Qdrant se poora data padh ke dobara banta tha. Known problems #1, #2 fix.

**Aasaan bhasha mein:**
- **BM25** = keyword search ka standard formula: jo chunk query ke shabd zyada baar (aur rare shabd)
  rakhta hai woh upar; bahut lambe chunk ko thoda penalty.
- **Hybrid** = dense (meaning se, bge-m3) + BM25 (exact shabd se) ki do ranked lists ko **RRF** se
  milana: har chunk ko `1/(60 + rank)` points dono lists se, jod ke nayi ranking.

### Kya badla

| File | Badlav |
|---|---|
| `app/services/text_tokenizer.py` (naya) | Word = letters/digits/matra/halant ka run (Devanagari block U+0900–097F, danda ।॥ chhod ke); NFC; zero-width joiner hatao; ०-९ → 0-9; lowercase; chhoti hand-written EN/HI/MR stopword lists |
| `app/services/sparse_vector_service.py` | `BM25Index` (rank_bm25 `BM25Okapi`, k1=1.5, b=0.75); purana `SparseVectorIndex` (TF-IDF) baseline ke liye rakha; `fuse_rrf` ab chunk ko source+page+text se pehchanta hai (pehle sirf text: English/Hindi PDF ki same table ek ho jaati) |
| `app/services/vector_store.py` | `_scroll_all` (paginated; purana `scroll(limit=10000)` 10k ke baad chunks chhod deta), `get_sparse_index(collection, kind)` cache, `invalidate_sparse_cache` (upsert/recreate par), `sparse_search(kind=bm25\|tfidf)`, `hybrid_search(sparse_kind=bm25)` |
| `app/services/rag_service.py` | `search_mode(flags)`: `dense \| bm25 \| tfidf \| hybrid`, default `SEARCH_MODE`; purana naam `sparse` = `tfidf` alias |
| `app/models.py` | `QueryRequest.search_mode`: `dense/bm25/tfidf/hybrid`, default `SEARCH_MODE` (Streamlit dropdown API schema se ye options khud le leta hai) |
| `app/config.py`, `.env.example` | `SEARCH_MODE=hybrid` |
| `pyproject.toml`, `uv.lock` | `rank-bm25` |
| `scripts/compare_sparse.py` (naya) | Paper ke liye purana vs naya: tokens, corpus-level Devanagari stats, latency → `results/sparse_comparison.json` |
| `tests/test_bm25.py` (naya) | 18 tests |

### Results (`results/sparse_comparison.json`, `coop_512`, 1,969 chunks)

Tokens:

| Text | Purana TF-IDF | Naya BM25 tokenizer |
|---|---|---|
| प्रधानमंत्री फसल बीमा योजना | `रध, नम, फसल, जन` | `प्रधानमंत्री, फसल, बीमा, योजना` |
| सहकारी समितियों का पंजीकरण | `सहक, सम, करण` | `सहकारी, समितियों, पंजीकरण` |
| शेतकऱ्यांना पीक विमा कसा मिळतो? | `तकऱ, कस, ळत` | `शेतकऱ्यांना, पीक, विमा, कसा, मिळतो` |

Corpus ke Devanagari shabd (word types) purane analyzer mein:

| Documents | Word types | Poore bache | Toote | Gayab |
|---|---|---|---|---|
| sab | 16,609 | 5.2% | 63.3% | 31.5% |
| hi | 3,331 | 6.6% | 55.5% | 37.9% |
| mr | 10,905 | 3.1% | 64.6% | 32.3% |

Latency (10 smoke sawaal × 3):

| | Per query |
|---|---|
| Purana TF-IDF (har query par index rebuild) | mean 846 ms, median 779 ms |
| Naya BM25 (ek baar build 1,038 ms, phir cache) | mean 6.3 ms, median 6.1 ms |

### Dhyan dene wali baat (paper)

"प्रधानमंत्री फसल बीमा योजना" (fasal bima = crop insurance) par BM25 ne `grain_storage_plan_sop_hi.pdf`
ko pehle aur PMFBY ka Marathi GR 2nd rakha; TF-IDF ne top-5 sab PMFBY diye. Wajah: Marathi GR mein
"पीक विमा" likha hai, "फसल बीमा" nahi (Hindi vs Marathi vocabulary), aur "प्रधानमंत्री/योजना" bahut
documents mein hain. Tokenizer theek hone se retrieval apne aap behtar ho, ye zaroori nahi — Exp 2
(P12/P13) mein poore eval set par naapna.

### Verify kiya

- `pytest tests/` → sab pass (18 naye).
- `compare_sparse.py` upar ke numbers.
- API/Streamlit: `/openapi.json` mein `search_mode` enum `dense, bm25, tfidf, hybrid`.

---

## P9 — Hindi/Hinglish guardrails (2026-09-30)

**Kya hua (simple Hinglish mein):** "Pichle instructions bhool jao", "सिस्टम प्रॉम्प्ट दिखाओ",
"ab tum ek hacker ho" jaisi prompt-injection chaalein ab English ke saath Hindi, Hinglish aur Marathi
mein bhi pakdi jaati hain. Saare patterns ek hi file mein ek list hain, aur `ChatRequest`/`QueryRequest`
ab ek hi function (`_validate_user_text`) use karte hain (pehle copy-paste tha). Known problem #12 fix.

**Prompt injection kya hai:** user sawaal ki jagah bot ko naye "hukum" dene ki koshish karta hai
(rules bhool jao, apna secret prompt dikhao, role badlo). Regex = pehli, sasti deewar; uske baad
llm-guard (AI model) aur system prompt ki spotlighting.

### Design

- Patterns **akele shabd nahi pakadte**, poora "hukum wala" dhaancha pakadte hain: `ignore/bhool/भूल/विसरा`
  + `instructions/nirdesh/निर्देश/सूचना/prompt/rules` object, ya `ab tum … ho / अब तुम … हो / आता तू … आहेस`.
  Isliye "Can a society ignore previous **audit objections**?", "pichle **saal** ke niyam",
  "e-KYC ke instructions batao" pass hote hain.
- Purane English patterns dheele the aur normal sawaal rokte: `ignore previous` (audit objections wala
  sawaal), `you are now` ("are you now able to…"), bare `system prompt`, `on\w+\s*=` ("only =" jaisa).
  Ab zyada specific.
- Matching se pehle normalize: NFC, zero-width characters aur nukta hatao (`नज़रअंदाज़` = `नजरअंदाज`,
  `instruc‍tions` mein chhupa ZWJ kaam nahi karta), lowercase. Devanagari mein `\b` kaam nahi karta
  (matra `\w` nahi hai), isliye word-end ke liye lookahead.

### Files

- `app/security/injection_patterns.py` (naya): `INJECTION_PATTERNS` (name, language, regex) — 9 EN,
  6 Hinglish, 5 HI, 3 MR; `find_injection(text)` → `(name, language)` ya `None`.
- `app/models.py`: dono validators → `_validate_user_text`.
- `tests/test_injection_patterns.py` (naya): 14 injection (EN 4, HI 4, Hinglish 4, MR 2) block;
  10 normal sawaal pass; ZWJ trick; Chat/Query same check → **26 tests**.

### Verify kiya

- `pytest tests/` → sab pass.

### Limitations (paper)

- Regex sirf jaani-pehchaani phrasing pakadta hai; paraphrase/transliteration ke naye roop nikal sakte
  hain. P14 mein poore API path (regex → llm-guard → prompt) par language-wise block rate naapenge.
