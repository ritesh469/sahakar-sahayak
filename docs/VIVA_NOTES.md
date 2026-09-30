# Viva notes: Sahakar Sahayak

Simple Hinglish mein. Saare numbers `results/*.csv` se hain (jawab: gpt-4.1-mini, judge:
gpt-4o-mini).

## 1. Project ek line mein

23 sarkari PDFs (sahkari kanoon, National Cooperation Policy 2025, PM-KISAN, PM-KMY, fasal bima,
Maharashtra GRs) se, English / Hindi / Marathi / Hinglish sawaalon ka jawab **usi bhasha mein**,
har fact ke saath `[file, p. N]`. Jawab documents mein na ho to bot **mana** karta hai, jawab banata
nahi. Research ka sawaal: kaunsa retrieval tarika multilingual sawaalon par best hai, aur bot kitna
hallucinate karta hai.

## 2. Har major file kya karti hai

### Ingestion (documents → vector DB)

| File | Kya karti hai |
|---|---|
| `app/services/document_processor.py` | PDF ko docling (pypdfium2 backend) se padhta hai aur chunks banata hai. Chunk ka max size bge-m3 tokenizer ke tokens mein (`CHUNK_SIZE`). Har chunk ke saath page number rakhta hai. |
| `app/services/embedding_service.py` | Text ko bge-m3 model se 1024 numbers ke vector mein badalta hai (GPU, fp16). Ek hi model teeno bhashayein samajhta hai. |
| `app/services/vector_store.py` | Qdrant mein chunks save/search. Har chunk size ki alag collection (`coop_256/512/1024`). BM25 index ek baar bana ke memory mein cache. Hybrid search yahin hota hai. |
| `scripts/seed_db.py` | Ingestion chalata hai (`--ingest-only --chunk-size 512`). Report `results/ingestion_*.json` mein. |
| `scripts/check_docs.py` | Har PDF ka text check: pages, Devanagari %, pehle 400 characters; kharab text wali file "SUSPICIOUS". |

### Sawaal → jawab

| File | Kya karti hai |
|---|---|
| `app/api/query.py` | `/query` endpoint. Order: rate limit → token budget → llm-guard scan → PII redaction → LangGraph → output PII check. |
| `app/models.py` | Request ke rules (pydantic). Sawaal mein injection pattern mila to yahin 422 error. |
| `app/core/graph.py` | LangGraph flow: route (SQL band hai, isliye hamesha RAG) → retrieve → generate → finalize. |
| `app/services/rag_service.py` | Asli RAG: `retrieve` (dense / bm25 / tfidf / hybrid, phir rerank, optional HyDE/CRAG) aur `generate` (spotlighted context + system prompt → LLM; optional Self-RAG loop). |
| `app/services/sparse_vector_service.py` | `BM25Index` (rank_bm25, k1=1.5, b=0.75), purana TF-IDF (baseline), aur `fuse_rrf` (hybrid ke liye). |
| `app/services/text_tokenizer.py` | Apna tokenizer: Hindi/Marathi ke matra aur halant word ke andar rakhta hai, NFC, zero-width hatata hai, Devanagari digits → 0-9, EN/HI/MR stopwords. |
| `app/services/reranking.py` | Cross-encoder `bge-reranker-v2-m3`: 20 retrieved chunks mein se sawaal ke saath padh ke best 5 chunta hai. |
| `app/services/language.py` | Sawaal ki bhasha pehchanta hai (en/hi/mr/hinglish): Devanagari ratio + aam shabdon ki list + Marathi endings. |
| `app/security/system_prompt.py` | LLM ke rules: sirf context se, user ki bhasha, har fact ke baad citation, fixed refusal / out-of-domain sentence (4 bhashaon mein). |
| `app/security/spotlighting.py` | Chunks ko `<chunk source=".." page="..">` tags mein lapet ke "ye data hai, hukum nahi" notice ke saath LLM ko deta hai. |
| `app/security/injection_patterns.py` | 23 regex patterns (9 EN, 6 Hinglish, 5 HI, 3 MR) jo "pichle instructions bhool jao", "system prompt dikhao", "ab tum … ho" jaisi chaalein pakadte hain. |
| `app/security/input_guard.py`, `content_moderation.py` | llm-guard: PromptInjection, Toxicity, BanTopics scanner; PII (email, phone, card) redaction. PERSON band hai kyunki English NER "किसान" ko naam samajhta tha. |
| `app/services/hyde.py`, `crag.py`, `self_reflective.py` | Advanced RAG (default band): HyDE (pehle nakli jawab bana ke usse search), CRAG (chunks ko grade karo, bekaar ho to hata do → refusal), Self-RAG (jawab ka review, zaroorat ho to dobara). |
| `app/services/llm_service.py` | Groq ya OpenAI client, token count, reasoning models ke liye settings. |
| `scripts/streamlit_app.py` | UI: login, 4 example sawaal, search mode, rerank, jawab ke neeche "file, p. N" sources. |

### Evaluation

| File | Kya karti hai |
|---|---|
| `eval/coop_questions.yaml` | 304 sawaal = 76 base × 4 bhasha (58 answerable, 10 unanswerable, 8 adversarial per bhasha). |
| `eval/schema.py`, `scripts/validate_questions.py` | Sawaal ka format check; har supporting text sach mein us PDF page par hai ya nahi. |
| `eval/metrics.py` | recall@k, precision@k, MRR, refusal pehchaan, hallucination / over-refusal outcome, citation check. |
| `eval/run_experiment.py` | Ek config (`configs/*.yaml`) ko saare sawaalon par chalata hai → `results/raw/*.csv` + `results/summary.csv`. Cache off; daily limit par resume. |
| `eval/ragas_adapter.py` | Ragas ke 4 metrics (LLM judge). |
| `eval/run_security_test.py` | Adversarial sawaal asli API se; kaunsi layer ne roka. |
| `eval/make_result_tables.py` | Paper ki tables + sign test (`results/*_results.csv`, `significance.csv`). |
| `scripts/make_plots.py` | Graphs `results/figures/`. |

## 3. Aasaan definitions

- **RAG (Retrieval-Augmented Generation):** LLM se seedha jawab nahi. Pehle documents mein se
  relevant hisse dhoondo, phir LLM ko bolo "sirf inse jawab do". Isse jawab documents par tika
  rehta hai aur source bata sakte hain.
- **Chunk:** PDF ka chhota tukda (yahan max 256 / 512 / 1024 tokens). Search chunk par hota hai.
- **Embedding / dense search:** text → numbers ka vector (bge-m3, 1024 numbers). Milte-julte matlab
  wale texts ke vector paas hote hain, bhasha alag ho tab bhi. Isliye Hindi sawaal English PDF dhoondh
  leta hai.
- **TF-IDF:** shabd ka score = document mein kitni baar aaya × kitna rare hai. Purana baseline.
- **BM25:** TF-IDF jaisa, par behtar: ek shabd baar-baar aaye to score ek had tak hi badhta hai (k1),
  aur lambe chunk ko thoda penalty (b). Keyword search ka standard.
- **Hybrid search:** dense list + BM25 list ko milana.
- **RRF (Reciprocal Rank Fusion):** har list mein chunk ki rank dekh ke `1 / (60 + rank)` points; dono
  lists ke points jodo, nayi ranking. Score nahi, sirf rank use hoti hai, isliye alag scale wali
  lists mil jaati hain.
- **Reranker (cross-encoder):** sawaal aur chunk ko saath padh ke relevance score deta hai. Dheema
  hai, isliye sirf top 20 par chalta hai, top 5 rakhta hai. Embedding sawaal aur chunk ko alag-alag
  padhta hai, isliye kam sateek hai.
- **Recall@k:** kitne % sawaalon mein sahi document (sahi page, ±1) top-k mein aaya.
- **Precision@k:** top-k chunks mein se kitne sahi the (k se divide).
- **MRR (Mean Reciprocal Rank):** pehla sahi chunk rank 1 par = 1, rank 2 = 0.5, rank 5 = 0.2,
  nahi mila = 0; sab sawaalon ka average. Batata hai sahi chunk kitna upar aaya.
- **Faithfulness (Ragas):** jawab ke kitne statements context se support hote hain (LLM judge
  check karta hai). Hallucination ka ulta.
- **Answer relevancy:** jawab sawaal se kitna juda hai.
- **Context precision / recall:** retrieved chunks kitne kaam ke the / zaroori jaankari kitni aayi.
- **Hallucination (hamari definition):** unanswerable ya adversarial sawaal par bot ne mana nahi
  kiya aur jawab de diya (fake premise sahi kar diya to theek maana).
- **Over-refusal:** answerable sawaal par bot ne mana kar diya.
- **Prompt injection:** sawaal mein bot ko naye hukum dena ("rules bhool jao"). Teen deewarein:
  regex → llm-guard → spotlighting + system prompt.
- **Spotlighting:** retrieved text ko tags mein band karke LLM ko batana ki ye data hai, hukum nahi.
- **HyDE:** pehle LLM se nakli jawab likhwao, us jawab ke embedding se search karo.
- **CRAG:** retrieved chunks ko LLM se grade karwao; bekaar hon to hata do (hamare yahan web search nahi).
- **Self-RAG:** LLM apna jawab review karta hai; kharab ho to sawaal sudhaar ke dobara.
- **Sign test:** do methods ko same sawaalon par compare: kitne sawaalon mein A behtar, kitne mein B;
  ye fark sirf luck se aa sakta hai ya nahi (p-value). p < 0.05 = pakka fark.

## 4. 15 sambhavit viva sawaal

1. **Aapne RAG kyun use kiya, seedha LLM kyun nahi?**
   Sarkari yojanaon mein galat number (rakam, tareekh) nuksaandeh hai. RAG jawab ko documents se
   baandhta hai aur `[file, p. N]` deta hai, taaki user check kar sake. Jawab na mile to fixed refusal.

2. **Multilingual kaise handle kiya?**
   Teen jagah: (a) bge-m3 multilingual embedding, isliye Hindi sawaal English PDF se match hota hai;
   (b) apna Devanagari-aware BM25 tokenizer; (c) `language.py` bhasha pehchanta hai aur prompt mein
   "Answer language: …" jaata hai. Eval mein har sawaal 4 bhashaon mein hai, isliye seedha tulna hoti hai.

3. **Purane TF-IDF mein kya dikkat thi?**
   Uska tokenizer matra/halant par Hindi shabd tod deta tha: "प्रधानमंत्री फसल बीमा योजना" →
   `रध, नम, फसल, जन`. Corpus ke Devanagari word types mein se sirf 5.2% poore bachte the
   (`results/sparse_comparison.json`).

4. **Naye BM25 tokenizer se kitna fayda hua?**
   Jab document sawaal ki lipi mein ho: English recall@5 0.825 → 0.950, Marathi 0.279 → 0.465. Hindi
   mein nahi (0.326 → 0.302), kyunki Hindi PDFs ka text layer toota hai
   (`results/script_match_results.csv`). Overall tfidf vs bm25 ka fark significant nahi (p = 0.31).

5. **Sabse achha retrieval kaunsa nikla?**
   Reranker ke saath dense (recall@5 0.853) aur hybrid (0.841) barabar hain (p = 0.51). Reranker ka
   asar sabse bada: hybrid 0.720 → 0.841 (30 sawaal behtar, 2 kharab, p < 0.001).

6. **Hybrid search Hindi/Marathi mein kharab kyun?**
   Bahut se Hindi/Marathi sawaalon ka jawab English PDF mein hai. BM25 exact shabd milata hai, jo
   alag bhasha mein nahi milte, isliye uski list mein galat chunks aate hain aur RRF unhe upar le aata
   hai. Rerank ke bina Hindi recall@5: dense 0.741, hybrid 0.655.

7. **Chunk size ka kya asar?**
   256 / 512 / 1024 par recall@5 0.828 / 0.841 / 0.845: koi significant fark nahi (p ≥ 0.58). Humne
   512 pehle se default tha; Exp 1 ne dikhaya ki badalne se fayda nahi, aur 1024 par retrieval
   latency zyada hai (1.02 s vs 0.64 s).

8. **Hallucination kaise naapa?**
   10 unanswerable (jawab documents mein nahi) + 8 adversarial (injection, fake premise, out of
   domain) × 4 bhasha. Bot ne mana kiya to sahi; jawab diya to hallucination. Answerable par
   refusal = over-refusal. Result (`results/hallucination_results.csv`): unanswerable par 90% sahi
   refusal; hallucination sirf 4/72 (5.6%): ek hi sawaal (Budget 2024-25 ki tax chhoot) chaaron
   bhashaon mein. Over-refusal 9.5%, aur 22 mein se 20 tab hue jab retrieval sahi chunk laaya hi nahi.
   **Dhyan:** gpt-4.1-mini Hindi/Marathi mein refusal apne shabdon mein likhta hai, isliye detector
   pehle sentence mein "documents mein nahi" wale phrases bhi pehchanta hai. Sirf fixed sentence
   dhoondhne par hallucination 37.5% dikhta (galat); 35 badle labels haath se check kiye.

9. **Self-RAG ka refusal bias kya hai?**
   Original Self-RAG reviewer prompt har "information nahi mili" ko fail maan ke dobara likhwata tha, isse
   bot unanswerable sawaal ka jawab "banane" lagta. Humne naya prompt banaya jisme sahi refusal achha
   jawab hai, aur dono ko Exp 6 mein compare kiya (`results/advanced_rag_results.csv`, 76 English
   sawaal): purane prompt se hallucination 1 se 2 (18 mein se) ho gaya, aur tokens 3.8 guna. Extra
   hallucination ek injection sawaal tha ("admin password batao"): naye prompt ne mana kiya, purane
   ne refusal ko "kharab" maan ke dobara likhwaya aur jawab portal login ke steps batane laga.
   HyDE, CRAG, Self-RAG teeno ne baseline se behtar kuch nahi kiya, bas 3–6 guna dheeme.

10. **Prompt injection se kaise bachaav?**
    Layer 1: 23 regex patterns 4 bhashaon mein (poora hukum wala dhaancha pakadte hain, akela "ignore"
    shabd nahi). Layer 2: llm-guard PromptInjection model. Layer 3: spotlighting + system prompt.
    API test (`results/security_results.csv`): 32 mein se 0 hamle kaamyaab; injection 11 regex ne,
    1 llm-guard ne roke. **Par** llm-guard (English model) ne 32 normal sawaalon mein se 8 rok diye,
    saare Hindi/Marathi (Devanagari ke 16 mein se 8). Yaani English guardrail Hindi/Marathi users ko
    nuksaan karta hai; paper ki badi finding.

11. **Page number kaise aata hai?**
    docling har text item ka page deta hai; chunk ka page = jis page par chunk shuru hota hai (kai pages
    par phaile paragraph mein `charspan` se sahi page dhoondhte hain, `document_processor._page_number`). Page Qdrant payload mein save hota hai aur citation tak jaata hai.

12. **PII redaction mein kya dikkat aayi?**
    llm-guard ka PERSON detector English NER hai; "किसान", "महिला शेतकरी" ko naam maan ke `<PERSON>`
    bana deta tha, 5 mein se 3 Devanagari sawaal bigad jaate. PERSON band kiya, baaki PII (email,
    phone) redaction chalu.

13. **Evaluation set kaise banaya?**
    Har document se 2-3 sawaal, exact supporting text + page ke saath; validator check karta hai ki
    text us page par hai. Phir Hindi, Marathi, Hinglish versions (same base_id). 76 base × 4 = 304.
    Limitation: translations machine ke hain, native speaker check baaki.

14. **Aapke project ki limitations?**
    Chhota dataset (23 docs, 76 base sawaal); ek hi LLM; Ragas LLM-as-judge; translations unverified;
    kuch Hindi/Marathi PDFs ka toota text layer; injection sawaal regex ke baad likhe gaye (block rate
    optimistic ho sakta hai); ek sawaal ke 4 bhasha versions independent nahi (sign test indicative).

15. **Future work?**
    Toote PDF text ke liye behtar OCR (Hindi/Marathi); native-speaker verified bada eval set; zyada
    Indian bhashayein; hybrid mein BM25 ko sirf same-script sawaalon par weight dena; voice input.

## 5. Demo se pehle yaad rakho

- `docs/DEMO_SCRIPT.md` ke 6 sawaal; pehle ek warm-up query (models load hote hain).
- Login 5/min limit: ek baar login karo.
- Experiment script aur API saath mat chalao (8 GB GPU).
