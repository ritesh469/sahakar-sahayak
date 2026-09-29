# Poora Project — Claude Code Prompts (Din 1 se Din 3 tak)

`CLAUDE.md` repo ke root folder mein hona chahiye. Har prompt ke saath ye loop follow karo:

1. **Plan mode** on karo (Shift+Tab).
2. Prompt paste karo aur plan padho.
3. Plan theek lage to "go ahead" bolo.
4. Claude se test chalwao.
5. Commit karwao.

Har **bada step** (P1, P2, …) ke baad `/clear` karo, taaki context saaf rahe.

`< >` ke andar wali jagah aapko khud bharni hai.

---

## Environment (P1 mein tay hua)

- OS: Windows 11. Project path: `C:\Projects\EnterpriseRAG` (OneDrive ke bahar, taaki `.venv` sync na ho).
- Python 3.12 via `uv` (`uv sync --extra dev`). `pyproject.toml` mein `link-mode = "copy"` hai
  (Windows par uv hardlink fail hota tha, os error 396).
- GPU: RTX 4060 (8 GB). PyTorch 2.12 CUDA 12.6 wheels `[tool.uv.sources]` se aate hain.
- **Ports (dusra project `retail-fde-project` 5432/6333/8000 use karta hai, aur ek native Windows
  Postgres 5433 par hai):** Postgres **5434**, Qdrant **6335** (gRPC 6336), FastAPI **8001**.
  `.env` mein `POSTGRES_HOST_PORT` etc. se set; `docker-compose.yml` inhe padhta hai.
- Docker: sirf `docker compose up -d postgres qdrant` (`app` service nahi chalate).
- Migrations: sirf `seed/migrations/001_create_users.sql`. `003_seed_k8s_ops.sql` SKIP (K8s SQL demo).
- Demo users: `scripts/seed_db.py` ki `DEMO_USERS` list (agent@demo.local, admin@demo.local).
- **Scripts hamesha `uv run --env-file .env python ...` se chalao.** `scripts/seed_db.py` DATABASE_URL
  `os.getenv` se padhta hai (default 5432 = dusre project ka DB!). Setup problem S1 dekho.
- LLM provider: **Groq** (chat). Groq embeddings nahi deta → embeddings local GPU model:
  **`BAAI/bge-m3`** (1024-dim, 8192 tokens, CUDA fp16), `.env`: `EMBEDDING_BACKEND=local`,
  `EMBEDDING_MODEL`, `EMBEDDING_DIM=1024` (P2). Chat (P5): `LLM_PROVIDER=groq`,
  `LLM_MODEL_ANSWER=openai/gpt-oss-120b`, `LLM_MODEL_GRADER=qwen/qwen3.8-27b`, `LLM_REASONING_EFFORT=low`.
  Reranker: `BAAI/bge-reranker-v2-m3` (local GPU).
- Chunking (P2): `CHUNK_SIZE` / `CHUNK_OVERLAP` tokens bge-m3 tokenizer se gine jaate hain.
  `PDF_BACKEND=pypdfium2` (S8 dekho).
- Qdrant collection = `{QDRANT_COLLECTION_PREFIX}_{chunk_size}` → `coop_256`, `coop_512`, `coop_1024`.
- Ingestion (Postgres ko chhoote bina):
  `uv run --env-file .env python scripts/seed_db.py --ingest-only --chunk-size 512 --noise-sample 0`
  (`--recreate` = collection pehle drop karo). **`--ingest-only` ke bina migrations chalenge (S1).**
- Documents (P3): K8s docs `seed/docs/_k8s_backup/` mein (ingest nahi hote). Naye docs `seed/docs/true_data/`.
  Check + `data/sources.csv` sync: `uv run --env-file .env python scripts/check_docs.py --write-sources`
  (`--pdf-backend docling_parse` se dono backends compare).
- OCR: docling ka RapidOCR Chinese/English models use karta hai → **scanned Hindi/Marathi PDF ka text nahi
  niklega** (`check_docs` SUSPICIOUS dikhayega). Aisi file hatao ya Unicode text wala version dhoondo.
- API server: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8001`

## Known problems

> **DRAFT (P1 ke baad Claude ne code padh ke likha) — user approval pending.**
> Numbering prompts ke hisaab se rakhi gayi hai (P2: #3–#6, P5: #7–#10 + #13, P8: #1–#2, P9: #12, P16: #11).

1. **Sparse search BM25 nahi, TF-IDF hai.** `sparse_vector_service.py` sklearn `TfidfVectorizer` use karta hai.
   Sparse index har query par Qdrant se dobara banta hai (`vector_store._build_sparse_index`, koi cache nahi),
   aur `scroll(limit=10000)` se 10k se zyada chunks chhoot jaate hain. (P8)
2. **Tokenizer Devanagari todta hai.** TF-IDF ka default `token_pattern` `\w\w+` hai; Python mein matra/halant
   (जैसे `ा`, `ि`, `्`) `\w` nahi hain, isliye Hindi/Marathi words tukdon mein toot jaate hain.
   Upar se `stop_words="english"` hai. **Verified (P1):** "प्रधानमंत्री फसल बीमा योजना" → TF-IDF tokens
   `['जन', 'नम', 'फसल', 'रध']` (बीमा poora gayab, sirf फसल sahi). (P8)
3. **(FIXED, P2)** ~~Config hardcoded.~~ Ab `CHUNK_SIZE`, `CHUNK_OVERLAP`, `EMBEDDING_DIM` `.env` se.
4. **(FIXED, P2)** ~~Docling device = MPS.~~ Ab `AcceleratorDevice.AUTO` (Windows par CUDA).
5. **(FIXED, P2)** ~~page_number gum ho jata hai.~~ Chunk → Qdrant payload → search/rerank/RRF/preview
   tak page jaata hai. Kai pages par phaila paragraph `charspan` se sahi page deta hai.
6. **(FIXED, P2)** ~~Ek hi Qdrant collection.~~ Ab har chunk size ki alag collection (`coop_512` etc.).
7. **(FIXED, P5)** ~~SQL path hamesha on + double routing.~~ `SQL_ENABLED=false` → router LLM call nahi,
   route hamesha "rag"; graph jo intent tay kare wahi `run_rag(intent=...)` ko jaata hai. SQL code rakha hai.
8. **(FIXED, P5)** ~~System prompt K8s SRE + JSON.~~ Ab cooperative/scheme assistant, plain text.
9. **(FIXED, P5)** ~~Multilingual/grounding rules nahi.~~ `app/services/language.py` sawaal ki language
   (en/hi/mr/hinglish) pehchaanta hai; prompt: sirf context, `[file, p. N]` citation, fixed refusal /
   out-of-domain sentences (4 languages, `system_prompt.REFUSAL_MESSAGES` — eval inhi ko dhoondhta hai).
10. **(FIXED, P5)** ~~CRAG default on + web fallback.~~ `CRAG_ENABLED_BY_DEFAULT=false`,
    `WEB_FALLBACK_ENABLED=false`; CRAG "incorrect" par web ki jagah chunks hata deta hai (→ refusal).
11. **Self-RAG refusal bias.** `self_reflective.py` ka prompt refusal ("I don't have information") ko
    fail maanta hai aur regenerate karwata hai → unanswerable sawaalon par hallucination badhega. (P16)
12. **Injection regex sirf English** (`models.py`), aur ChatRequest/QueryRequest mein duplicate. (P9)
13. **(FIXED, P5)** ~~Spotlighting mein page number nahi~~; `<chunk ... page="N">`. Graph ka `retrieve_rag`
    ab asli chunks deta hai (`rag_service.retrieve`).

### Setup problems (P1 mein mile, abhi fix nahi kiye)

- **S1.** `scripts/seed_db.py` `.env` nahi padhta (`os.getenv("DATABASE_URL")`, default 5432), aur
  `run_migrations` SAARI .sql files chalata hai (003 mein `DROP TABLE ... CASCADE`). Galat DB par chala to data udega.
- **S2. (FIXED, P1 follow-up)** Rate limiter aur token budget ko Upstash Redis zaroori tha → `/auth/login`
  500 deta tha. Ab Upstash na ho to in-memory fallback (`tests/test_redis_fallback.py`).
  Dhyan do: login limit 5/min per IP hai (`AUTH_LOGIN_RATE_LIMIT_PER_MIN`) — P14 mein ek hi token reuse karo.
- **S3. (FIXED, P5)** ~~`llm_service.py` import par OpenAI client~~ → `get_client()` lazy; `LLM_PROVIDER=groq`
  (Groq base_url), `LLM_MAX_RETRIES` (429 par SDK retry). `OPENAI_API_KEY` placeholder ab zaroori nahi.
- **S4.** `middleware/auth.create_access_token`: `expires_delta_seconds` pass karne par `expire` undefined (bug).
- **S5. (FIXED, P5)** ~~Reranker har query par model load~~ → CrossEncoder model-name ke hisaab se cache (fp16 CUDA).
- **S6.** Windows console (cp1252) Hindi/Marathi print karne par `UnicodeEncodeError` deta hai →
  scripts `PYTHONIOENCODING=utf-8` ke saath chalao (ya script mein `sys.stdout.reconfigure(encoding="utf-8")`).
- **S7. (P2 mein mila)** Windows Developer Mode off → HF cache symlink nahi bana sakta. `snapshot_download`
  8 threads mein chalta hai aur symlink-check mein race hai → `OSError: [WinError 1314]`, snapshot adhoora.
  Naya HF model pehli baar ek thread se download karo:
  `uv run python -c "from huggingface_hub import snapshot_download as s; s('<repo>', revision='<rev>', max_workers=1)"`
  (docling: `docling-project/docling-models` rev `v2.3.0`, `docling-project/docling-layout-heron` rev `main`).
  Developer Mode on karne se ye (aur duplicate copies se disk waste) khatam ho jaayega.
- **S8. (P2 mein mila, workaround)** Docling ka default PDF backend (docling-parse) kuch pages par
  `std::bad_alloc` deta hai aur page chupchap chhod deta hai (K8s PV PDF: 16 mein se 12–14 pages).
  `PDF_BACKEND=pypdfium2` se 16/16 pages. Ab `process_document` missing pages ka WARNING log karta hai.
- **S9. (P5 mein mila, workaround)** Windows par `grpc` (qdrant_client) + `psycopg2` + `torch` load hone ke
  BAAD `pyarrow.dataset` load ho (sentence_transformers → datasets → pandas) to process segfault
  (access violation) — koi Python error nahi, seedha exit 139. Repro:
  `python -c "import grpc, psycopg2, torch, pyarrow.dataset"`. Fix: `app/__init__.py` Windows par
  `pyarrow.dataset` sabse pehle import karta hai. Naya script `app` import se pehle ye teeno import kare
  to wahi crash aa sakta hai → `import app` sabse upar rakho.

---

# DIN 1 — Core chatbot

## P1 — Project chalu karna

```
CLAUDE.md padho. Abhi koi feature mat badlo.
Mera OS <Windows/Mac/Linux> hai. Step-by-step project chalane mein help karo:
1) dependencies install (uv ya pip; Windows par `make` nahi hai to equivalent commands do),
2) `docker compose up -d postgres qdrant`,
3) sirf seed/migrations/001_create_users.sql chalao + demo users banao (003 K8s SQL skip),
4) FastAPI start karke /admin/health check karo.
Har error ka root cause batao, phir fix karo. Har step ke baad simple Hinglish mein batao kya hua.
Aakhir mein CHANGELOG.md banao aur pehli entry likho.
```

## P2 — Config, chunking, page number

```
CLAUDE.md ke Known problems #3, #4, #5, #6 fix karne hain. Pehle plan dikhao.
- app/config.py: CHUNK_SIZE, CHUNK_OVERLAP, EMBEDDING_DIM, QDRANT_COLLECTION_PREFIX (.env se).
- document_processor.py: chunker ka max token CHUNK_SIZE se; device AUTO; har chunk ke saath page_number.
- RetrievedChunk + RetrievedChunkPreview mein optional page_number; seed_db.py aur vector_store.py
  page_number Qdrant payload mein save karein aur search results mein wapas dein.
- Collection ka naam = f"{prefix}_{chunk_size}"; seed_db.py mein --chunk-size argument.
Ek pytest likho jo ek chhota document ingest karke check kare ki chunks mein page_number hai.
Test chalao, CHANGELOG.md update karo, commit karo.
```

## P3 — Documents check

```
seed/docs/true_data/ ke Kubernetes documents seed/docs/_k8s_backup/ mein move karo (delete nahi).
Maine naye documents seed/docs/true_data/ mein daale hain.
scripts/check_docs.py banao: har document ka naam, pages, language guess (Devanagari characters ka %),
aur pehle 400 characters ka extracted text print kare. Jin files ka text garbage lage (bahut kam
Devanagari/Latin letters, ajeeb symbols) unhe "SUSPICIOUS" mark kare.
data/sources.csv ka template banao (filename,title,source_url,download_date,language,category)
aur filenames already bhar do; URL main bharunga.
```

(Yahan ruko. SUSPICIOUS files khud dekho, aur jo kharab hain unhe hata do.)

## P4 — Ingestion

```
CHUNK_SIZE=512 ke saath saare documents ingest karo (noise sample 0).
Report karo: kitne documents, kitne chunks, average chunk length, kitne fail hue aur kyun.
Ye numbers results/ingestion_512.json mein save karo.
```

## P5 — Domain, grounding, multilingual answer

```
CLAUDE.md ke Known problems #7, #8, #9, #10, #13 fix karo. Pehle plan dikhao.
- SQL_ENABLED=false: router bypass, route hamesha "rag", graph mein double routing hatao. SQL code delete mat karo.
- system_prompt.py: cooperative governance / government scheme assistant.
  Rules: sirf context se jawab; user ki language mein jawab (English/Hindi/Marathi/Hinglish);
  har fact ke baad [source, p. N]; context kam ho to fixed refusal sentence (user ki language mein);
  domain ke bahar ke sawaal par polite mana; plain text output (JSON nahi).
- spotlighting.py mein page number bhi dikhao.
- WEB_FALLBACK_ENABLED=false, CRAG_ENABLED_BY_DEFAULT=false.
- .env: RERANKER_MODEL=BAAI/bge-reranker-v2-m3, LLM_MODEL_ANSWER aur LLM_MODEL_GRADER = <model>.
Ek test query chala ke dikhao ki naya LLM model repo ke code ke saath chalta hai.
```

## P6 — Streamlit UI cleanup

```
scripts/streamlit_app.py mein chhote badlav (logic mat todo):
- Title/branding: "Sahakar Sahayak — Cooperative & Scheme Assistant" (K8s badge hatao).
- SQL approval tab aur upload tab chhupao (config flag se).
- Search mode dropdown mein bm25 option ka jagah bana do (Din 2 mein kaam karega).
- Answer ke neeche sources "filename, p. N" format mein.
- Sidebar mein 4 example sawaal (English, Hindi, Marathi, Hinglish) — main dunga: <sawaal>.
```

## P7 — Din 1 gate: smoke test

```
scripts/smoke_test.py banao jo ye sawaal rag_service se chalaye aur answer, sources (page ke saath)
aur latency print kare:
<2 English, 2 Hindi, 2 Marathi, 2 Hinglish, 1 unanswerable, 1 out-of-domain sawaal>
Batao kaunse sawaal par sahi document top-5 mein nahi aaya aur kyun ho sakta hai.
Commit karo: "Day 1: baseline multilingual RAG working".
```

---

# DIN 2 — Retrieval + Evaluation

## P8 — Asli BM25 + Devanagari tokenizer

```
CLAUDE.md ke Known problems #1 aur #2 fix karo. Pehle plan dikhao.
- app/services/text_tokenizer.py: Unicode-aware tokenizer jo Devanagari matras/halant (ऀ-ॿ)
  ko word ke andar rakhe, lowercase kare, punctuation hataye. English, Hindi aur Marathi ke liye
  chhoti stopword list (khud likhi hui, file mein).
- sparse_vector_service.py: BM25Index class (rank_bm25 BM25Okapi) is tokenizer ke saath.
  Purana TF-IDF class bhi rahe.
- SEARCH_MODE: bm25 | tfidf | dense | hybrid. Hybrid = dense + BM25 via RRF.
- Sparse index har collection ke liye ek baar bane aur memory mein cache ho.
- models.py: QueryRequest.search_mode mein naye options.
Tests: "प्रधानमंत्री फसल बीमा योजना" ke tokens poore words hon; purane TF-IDF ka output bhi print karo
(ye paper mein comparison ke liye chahiye). Latency pehle vs baad print karo.
```

## P9 — Hindi/Hinglish guardrails

```
CLAUDE.md Known problem #12. models.py ke regex injection patterns mein Hindi aur Hinglish variants add karo
(jaise "pichle instructions bhool jao", "पिछले निर्देश भूल जाओ", "system prompt dikhao", "ab tum ... ho").
Patterns ek list mein, ek jagah. 10 tests likho: 5 injection (EN/HI/Hinglish) block hon,
5 normal sawaal (jisme "ignore" jaisa word normal context mein ho) pass hon.
```

## P10 — Evaluation dataset banana

```
eval/coop_questions.yaml banana hai, CLAUDE.md ke format mein.
Step 1: har document se 2-3 answerable sawaal SUGGEST karo, saath mein exact supporting text,
filename aur page. Sirf wahi jo text mein clearly likha hai. Mujhe list dikhao, file mein mat likho.
Step 2 (main approve karunga): approved English sawaalon ke Hindi, Marathi, Hinglish versions banao,
same base_id aur same relevant_documents ke saath.
Step 3: 10 unanswerable sawaal (topic domain ka hai par jawab documents mein nahi, jaise kisi scheme
ki exact amount jo likhi nahi) aur 8 adversarial (prompt injection, fake premise, out-of-domain),
charon bhashaon mein mix.
eval/schema.py mein naya CoopGolden model aur loader; validate script jo check kare ki har
relevant_document sach mein seed/docs/true_data/ mein hai.
```

(Yahan dhyan se khud check karo. Har expected answer document mein dekho, aur Hindi/Marathi translations kisi native speaker se verify karwao.)

## P11 — Metrics + eval runner

```
eval/ mein naya runner eval/run_experiment.py banao (purana run_ragas.py rahe). Pehle plan dikhao.
- Input: --config configs/<name>.yaml (chunk_size, search_mode, rerank, hyde, crag, self_rag, top_k),
  --questions eval/coop_questions.yaml, --no-ragas option.
- Har sawaal: retrieval latency, generation latency, total latency alag measure (cache off).
- eval/metrics.py: recall_at_k, precision_at_k, mrr (relevant = source match, page diya ho to page bhi),
  refusal_detected (answer mein refusal sentence ya uske HI/MR versions),
  hallucination flags: unanswerable par refusal nahi = hallucination; answerable par refusal = over-refusal.
- Ragas (faithfulness, answer_relevancy, context_precision, context_recall) reuse, optional.
- Output: results/raw/<config>_<timestamp>.csv (per-question) + results/summary.csv mein ek row
  (config + aggregate metrics, language-wise bhi).
Pehle metrics.py ke unit tests chhote hand-made examples par likho aur chalao.
Phir 5 sawaalon par dry run karo aur output dikhao.
```

## P12 — Experiment configs + saare indexes

```
configs/ folder mein ye YAML banao (sirf ek variable badle):
exp1_chunk_256, exp1_chunk_512, exp1_chunk_1024  (hybrid + rerank)
exp2_bm25, exp2_tfidf, exp2_dense, exp2_hybrid    (512, no rerank)
exp3_hybrid, exp3_hybrid_rerank                   (512)
exp6_hyde, exp6_crag, exp6_selfrag                (512, hybrid + rerank + ek feature)
Phir chunk size 256 aur 1024 ke collections bhi ingest karo aur ingestion stats save karo.
scripts/run_all_experiments.sh (aur Windows ke liye .ps1) banao jo Exp 1–3 chalaye.
```

(Raat ko indexing chala ke chhod do.)

---

# DIN 3 — Experiments, graphs, paper, demo

## P13 — Experiments 1–5 chalana

```
run_all_experiments chalao (Ragas ke saath). Phir:
- Exp 4 (language): best config ke results language-wise split karo → results/multilingual_results.csv
- Exp 5 (hallucination): answerable / unanswerable / adversarial ke hisaab se refusal rate,
  hallucination rate, over-refusal rate → results/hallucination_results.csv
- Exp 1/2/3 → results/chunking_results.csv, retrieval_results.csv, reranking_results.csv
Har file mein config, date, question count, aur model names ho.
Koi run fail ho to batao, number khud mat bharna.
```

## P14 — Guardrail test (API path)

```
eval/run_security_test.py: adversarial sawaalon ko FastAPI /query endpoint se bhejo (login ke saath),
taaki saare guardrail layers chalen. Record karo: kaunsi layer ne block kiya (regex, llm-guard, prompt),
ya answer aaya. Language-wise block rate → results/security_results.csv.
```

## P15 — Graphs

```
scripts/make_plots.py: sirf results/*.csv padh ke matplotlib graphs banao → results/figures/:
recall_at_k.png, mrr.png, chunk_size.png, rerank_effect.png, faithfulness.png,
hallucination_rate.png, latency.png, language_wise.png.
Har graph par axis labels, units, aur question count (n=..). Ek hi command se sab bane.
```

## P16 — (Optional, time ho to) Experiment 6

```
CLAUDE.md Known problem #11: self_reflective.py prompt mein rule add karo ki documents mein
jawab na ho to sahi refusal ek achha answer hai. Purana prompt bhi flag se rakho (comparison ke liye).
exp6_hyde, exp6_crag, exp6_selfrag (dono prompts) chalao → results/advanced_rag_results.csv.
```

## P17 — Paper draft

```
paper/ folder mein paper.md likho, title:
"Multilingual and Hallucination-Aware Retrieval-Augmented Generation for Cooperative Governance
and Government Scheme Assistance".
Sections: Abstract, Introduction, Problem Statement, Research Gap, Related Work, Methodology,
System Architecture, Dataset, Experimental Setup, Evaluation Metrics, Results, Discussion,
Limitations, Conclusion, References.
Rules:
- Har number sirf results/*.csv se; table ke neeche file ka naam likho.
- Dataset stats sirf data/sources.csv, results/ingestion_*.json aur eval/coop_questions.yaml se count karke.
- Graphs results/figures/ se embed karo.
- Related Work aur References: sirf wahi papers jo main dunga ya jinka exact title/link tum verify kar sako;
  jahan unsure ho wahan [CITATION NEEDED] likho, fake reference mat banao.
- Discussion mein findings: TF-IDF Devanagari tokenization issue, BM25 fix ka asar,
  Self-RAG refusal bias (agar Exp 6 chala), English-only guardrails.
- Limitations imaandari se: chhota dataset, ek hi LLM, LLM-as-judge metrics, manual translation.
```

## P18 — Demo + README

```
1) docs/DEMO_SCRIPT.md: 6 demo sawaal (EN, HI, MR, Hinglish, 1 unanswerable, 1 injection),
   har ek ke saath expected behaviour aur kya dikhana hai.
2) README.md ko naye project ke liye update karo: kya hai, architecture diagram (mermaid),
   setup steps (Windows + Mac/Linux), kaise ingest karein, kaise experiments chalayein, results kahan hain.
   Purana K8s README docs/README_original.md mein rakho.
3) Poore project ka final check: tests chalao, app start karo, 3 demo sawaal chala ke dikhao.
Final commit: "Day 3: experiments, paper draft, demo ready".
```

## P19 — Viva prep (bonus)

```
docs/VIVA_NOTES.md banao: har major file 2-3 line mein simple Hinglish mein kya karti hai,
RAG / BM25 / dense / hybrid / RRF / reranker / faithfulness / MRR ki aasaan definitions,
aur 15 likely viva sawaal + unke chhote jawab, sirf is project ke asli code aur results ke basis par.
```

---

## Agar kuch atak jaye

- **Error aaye to:** "Ye error aaya: <poora error>. Root cause dhoondo, fix se pehle batao kya badal rahe ho."
- **Samajh na aaye to:** "<file> ko final-year viva ke level par simple Hinglish mein samjhao."
- **30 min se zyada atak jaye to:** feature ko config se off karo, aage badho, aur Limitations mein likh do.
- **Context bhar jaye (Claude bhoolne lage) to:** `/clear` karo, phir bolo "CLAUDE.md aur CHANGELOG.md padh ke continue karo, abhi <P number> par hain".
