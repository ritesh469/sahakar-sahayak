# Multilingual and Hallucination-Aware Retrieval-Augmented Generation for Cooperative Governance and Government Scheme Assistance

**Ritesh Kumar, [Department], [Institution]**

> **Draft status (2026-09-30).** All experiments are complete, and every number is copied from
> `results/*.csv` with the file named under each table. Before submission, still to do: author
> details and a native-speaker check of the Hindi, Marathi and Hinglish questions (Section 12).

---

## Abstract

Farmers and members of cooperative societies in India need accurate answers about cooperative
law and government schemes, often in Hindi, Marathi or code-mixed Hinglish, while most official
documents are in English or have damaged Devanagari text layers. We build and evaluate a
retrieval-augmented generation (RAG) assistant over 23 official documents (673 pages) that answers
in the user's language, cites file and page for every fact, and refuses when the documents do not
contain the answer. We evaluate on 304 questions: 76 base questions, each in English, Hindi,
Marathi and Hinglish, covering answerable, unanswerable and adversarial questions. On the 232
answerable questions, multilingual dense retrieval (bge-m3) reaches recall@5 0.728, against 0.487
for BM25 and 0.457 for TF-IDF. A cross-encoder reranker raises recall@5 to 0.853 (dense) and 0.841
(hybrid). The reranker gain is significant (p < 0.001, sign test). The difference between dense
and hybrid retrieval after reranking is not. Without reranking, hybrid fusion hurts Hindi and
Marathi questions (MRR 0.401 vs 0.603 for Hindi, p < 0.001), because many of them are answered by
English documents that lexical matching cannot reach. A Devanagari-aware BM25 tokenizer helps when
question and document share a script (Marathi recall@5 0.279 to 0.465), but not for Hindi
documents with damaged text layers. With gpt-4.1-mini as the generator, the assistant answers in
the question's language 99.3% of the time and refuses 90% of unanswerable questions. It
hallucinates on 4 of 72 unanswerable or adversarial questions, all four being language versions of
one temporal false-premise question. Twenty of the 22 over-refusals follow a retrieval miss. HyDE,
CRAG and Self-RAG do not reduce hallucination and increase latency 3–6×. Self-RAG with its
original reviewer prompt, which treats refusals as failures, doubles hallucination (2 vs 1 of 18
questions). In one case it abandons a correct refusal of a prompt injection; a refusal-aware
reviewer prompt avoids this. Finally, an English-trained prompt-injection classifier (LLM Guard)
blocked 8 of 16 legitimate Hindi and Marathi questions and none of the English or Hinglish ones.

**Keywords:** retrieval-augmented generation, multilingual retrieval, Hindi, Marathi,
code-mixing, hallucination, cooperative governance, government schemes, BM25, reranking.

---

## 1. Introduction

India's cooperative sector and its welfare schemes are documented in Acts, rules, policies,
operational guidelines and state government resolutions (GRs). The people these documents are
meant for (farmers, members of primary agricultural credit societies (PACS), cooperative staff)
often read Hindi or Marathi better than English, and frequently write in Hinglish, a Latin-script
mix of Hindi and English. In the 2011 Census, 43.63% of India's population reported Hindi and
6.86% Marathi as their language, while only about 0.26 million people reported English as their
mother tongue [Census2011]. Awareness is a known barrier to scheme uptake: in the NSS 70th round
(2012–13), 44.2% of the farmers who had not insured their crops said they were not aware of crop
insurance, and another 17.5% did not know the facility was available [Mukherjee2019]. An
assistant for these users therefore has to answer accurately in their languages.

Large language models (LLMs) can answer such questions fluently, but a fluent wrong answer about a
subsidy amount, an eligibility age or a deadline can cost a farmer money. Retrieval-augmented
generation (RAG) [Lewis2020] grounds the answer in retrieved documents, but three questions remain
open for this setting:

1. **Retrieval across languages and scripts.** Does multilingual retrieval work when a Hindi or
   Marathi question must be answered from an English PDF, and does classical lexical search (BM25)
   still help once Devanagari is tokenized correctly?
2. **Grounding and refusal.** Does the system refuse when the documents do not contain the
   answer, or does it hallucinate? Does it refuse too often when the answer is present?
3. **Safety across languages.** Do guardrails that were designed for English stop prompt
   injection written in Hindi, Marathi or Hinglish, and do they damage legitimate Devanagari input?

This paper makes the following contributions:

- A working multilingual RAG assistant for cooperative governance and government schemes, with
  page-level citations and fixed refusal messages in four languages.
- A 304-question evaluation set: 76 base questions × 4 languages, with gold file and page for
  every answerable question.
- A controlled comparison of TF-IDF, BM25 with a Devanagari-aware tokenizer, dense, hybrid (RRF)
  and reranked retrieval, split by language and by whether the answer document shares the
  question's script, with paired significance tests.
- An analysis of two failure sources specific to Indian-language documents: tokenizers that break
  Devanagari words, and PDF text layers that are already broken.
- Hallucination and over-refusal rates per language and question type, with a refusal detector
  that handles paraphrased refusals in four languages.
- A comparison of HyDE, CRAG and Self-RAG, including evidence that a refusal-penalising Self-RAG
  reviewer increases hallucination, and a refusal-aware reviewer prompt that avoids it.
- A per-layer guardrail analysis in four languages, showing that an English-trained injection
  classifier blocks legitimate Devanagari questions.

## 2. Problem Statement

Given a question *q* in English, Hindi, Marathi or Hinglish and a fixed corpus *D* of official
cooperative and scheme documents, the system must:

1. retrieve the passages of *D* that contain the answer, even when *q* and the passage are in
   different languages or scripts;
2. generate an answer in the language of *q*, using only the retrieved passages, with a
   `[file, p. N]` citation after each fact;
3. return a fixed refusal sentence (in the language of *q*) when *D* does not contain the answer,
   and a fixed out-of-domain sentence for unrelated questions;
4. resist prompt-injection and false-premise questions in all four languages.

We measure (1) with recall@k, precision@k and MRR against gold file and page. We measure (2) and
(3) with refusal detection, hallucination rate, over-refusal rate, answer-language match and
Ragas metrics. We measure (4) by which guardrail layer stops each adversarial question.

## 3. Research Gap

Published RAG techniques (hybrid search, reranking, HyDE [Gao2022], CRAG [Yan2024],
Self-RAG [Asai2023]) are usually evaluated on English benchmarks. Multilingual retrieval
benchmarks such as MIRACL [Zhang2022] evaluate retrieval within one language at a time, not a
Hindi question against an English-only document collection. The closest systems are
Farmer.Chat [Singh2024], a deployed multilingual RAG chatbot for agricultural advice (including
Hindi in India) evaluated with Ragas faithfulness, context precision and answer rate aggregated
over all languages, and AgriGov [Bilal2026], an English–Hindi–Marathi dataset curated from 50
Indian government schemes for farmers. Farmer.Chat does not report results per language, for
code-mixed questions or for prompt injection, and AgriGov, from its abstract, releases a dataset
without evaluating a RAG system. In our (non-exhaustive) literature search we did not find an
evaluation of RAG for Indian cooperative-governance and scheme documents that (a) uses parallel
questions in English, Hindi, Marathi and Hinglish, (b) separates same-script from cross-script
retrieval, (c) measures hallucination and over-refusal per language, and (d) tests guardrails
against non-English injection. Practical issues of such corpora (damaged
Devanagari text layers in official PDFs, English-trained named-entity recognisers in PII filters)
are also rarely reported.

## 4. Related Work

**Retrieval-augmented generation.** Lewis et al. [Lewis2020] combine a dense retriever with a
sequence-to-sequence generator, so that answers are conditioned on retrieved passages. Our
system follows the same retrieve-then-generate pattern with an instruction-tuned LLM and prompt-level
grounding rules instead of joint training.

**Lexical, dense and hybrid retrieval.** BM25 [Robertson2009] remains a strong lexical baseline.
Dense retrievers embed queries and passages in one vector space; M3-Embedding (bge-m3) [Chen2024]
supports more than 100 languages and long inputs, which makes it a natural choice for mixed
English/Hindi/Marathi corpora. Reciprocal rank fusion (RRF) [Cormack2009] combines ranked lists
using only ranks, and is the usual way to build hybrid dense + lexical retrieval. Cross-encoder
rerankers re-score a short candidate list by reading query and passage together; we use
bge-reranker-v2-m3 [BGERerank], which is built on bge-m3.

**Advanced RAG.** HyDE [Gao2022] retrieves with the embedding of a hypothetical answer generated
by the LLM. Corrective RAG (CRAG) [Yan2024] grades retrieved documents and triggers corrective
actions (in the original, web search) when they are judged irrelevant. Self-RAG [Asai2023] trains
a model to critique its own retrieval and generations; we use a prompt-based variant in which an
LLM reviewer scores the answer and may request a regeneration.

**RAG evaluation.** Ragas [Es2023] defines reference-free metrics (faithfulness, answer
relevancy, context precision and recall) computed with an LLM judge. We complement these with
retrieval metrics against gold file and page and with explicit refusal-based hallucination
accounting.

**Prompt injection.** Spotlighting [Hines2024] marks untrusted input (here: retrieved chunks) so
that the model can tell data from instructions. LLM Guard [LLMGuard] provides model-based input
and output scanners (prompt injection, toxicity, banned topics, PII).

**Multilingual retrieval and Indian languages.** MIRACL [Zhang2022] is a multilingual retrieval
benchmark across 18 languages. FIRE [Majumder2010] built the first TREC-style test collections
for Indian-language IR, including Hindi and Marathi. Hindi-BEIR [Acharya2024] collects 15 Hindi
retrieval datasets across 8 tasks, and IndicIRSuite [Haq2024] provides a machine-translated
MS MARCO and monolingual ColBERT retrievers for 11 Indian languages, including Hindi and Marathi.
IndicXTREME [Doddapaneni2023] is a human-supervised NLU benchmark for 20 Indic languages.
Hinglish questions are transliterated, so Roman-script query words must match terms that
documents write in Devanagari; Gupta et al. [Gupta2014] address this mixed-script retrieval
problem by modelling terms from both scripts jointly.

**Agricultural and government-scheme assistants.** Farmer.Chat [Singh2024] answers farmers'
questions over expert-vetted documents in four countries and several languages, including Hindi,
Odia and Telugu in India. AgriGov
[Bilal2026] curates a trilingual (English, Hindi, Marathi) dataset of Indian government schemes
for farmers, intended for question answering, retrieval and translation.

**Document conversion.** Docling [Auer2024] converts PDFs into structured documents with page
provenance, which we use for page-level citations.

## 5. Methodology

### 5.1 Document processing and chunking

PDFs are converted with Docling [Auer2024] using the pypdfium2 PDF backend. The default backend
skipped pages with a memory error on some documents; pypdfium2 converted all pages (Section 7).
Docling's hybrid chunker splits the document at headings and paragraphs, with a maximum chunk
length measured in bge-m3 tokens (`CHUNK_SIZE` ∈ {256, 512, 1024}) and no overlap. Each chunk
stores its source file and the page on which it starts. For a paragraph that spans pages, the page
is found from the character span of each page inside the paragraph. Each chunk size is stored in a
separate Qdrant collection.

### 5.2 Retrieval

- **Dense:** the question is embedded with bge-m3 (1024 dimensions, fp16 on GPU), and the nearest
  chunks by cosine similarity are returned from Qdrant.
- **TF-IDF (baseline):** the original system's sparse index. Its analyzer splits Devanagari words
  at vowel signs (matras) and the virama (halant), so most Hindi and Marathi words are broken or
  dropped (Section 11.1).
- **BM25:** BM25Okapi (k1 = 1.5, b = 0.75) from rank_bm25 [RankBM25] with our tokenizer. A token is
  a maximal run of letters, digits, Devanagari vowel signs and virama. Text is NFC-normalised,
  zero-width joiners are removed, Devanagari digits are mapped to ASCII, and it is lowercased.
  Small hand-written English, Hindi and Marathi stopword lists are applied. The index is built
  once per collection and cached.
- **Hybrid:** dense and BM25 lists are fused with RRF [Cormack2009], score = Σ 1/(60 + rank).
- **Reranking:** when enabled, 20 candidates are retrieved and bge-reranker-v2-m3 keeps the best 5.
  Otherwise the top 5 are used directly.

### 5.3 Grounded multilingual generation

The five retrieved chunks are wrapped in spotlighting tags [Hines2024], one
`<chunk source=".." page="..">` element per chunk, preceded by a notice that the content is
untrusted data, not instructions. A rule-based detector classifies the question as English,
Hindi, Marathi or Hinglish. It uses the Devanagari character ratio, lists of frequent function
words, and Marathi suffixes to separate Hindi from Marathi. The system prompt instructs the model
to:

1. answer only from the context;
2. answer in the detected language;
3. place a `[file, p. N]` citation after each fact;
4. reply with a fixed refusal sentence when the context does not contain the answer;
5. reply with a fixed out-of-domain sentence for unrelated questions;
6. output plain text.

The fixed sentences exist in all four languages, so refusals can be detected automatically.

### 5.4 Advanced RAG variants (Experiment 6)

- **HyDE:** the LLM writes a hypothetical answer, and its embedding is used for retrieval.
- **CRAG:** a grader LLM scores the relevance of the retrieved chunks. Below a threshold of 0.7
  the chunks are removed, so the model must refuse. Unlike the original CRAG there is no web
  fallback: an answer from the open web would not be grounded in official documents.
- **Self-RAG (prompt-based):** a reviewer LLM scores relevance, accuracy, completeness and clarity
  and may request a regeneration with a refined question (at most 2 retries). We compare two
  reviewer prompts:
  - *Original:* inherited from the base system. It treats any refusal as a failed answer.
  - *Refusal-aware:* it treats a correct refusal as a good answer and inventing facts as worse
    than refusing.

### 5.5 Guardrails

Requests pass, in order, through:

1. a regex layer of 23 prompt-injection patterns: 9 English, 6 Hinglish, 5 Hindi, 3 Marathi. They
   match instruction-override or role-change structures, not single words such as "ignore";
2. a per-user rate limit and daily token budget;
3. LLM Guard input scanners (prompt injection, toxicity, banned topics);
4. PII redaction of the input;
5. spotlighting in the prompt;
6. PII redaction of the output.

The PERSON entity of the PII scanner is disabled: its English named-entity model tagged ordinary
Devanagari words such as किसान ("farmer") as person names and corrupted Hindi and Marathi questions
before they reached the LLM (Section 11.4).

## 6. System Architecture

```mermaid
flowchart LR
    U[User: EN / HI / MR / Hinglish] --> API[FastAPI /query]
    API --> G[Guardrails: regex, rate limit, LLM Guard, PII]
    G --> LG[LangGraph: retrieve, generate, finalize]
    LG --> RET[Retriever: dense / BM25 / hybrid RRF]
    RET --> QD[(Qdrant: coop_256 / 512 / 1024)]
    RET --> RR[bge-reranker-v2-m3]
    RR --> GEN[LLM with spotlighted context and grounding prompt]
    GEN --> OUT[PII check, answer with file and page citations]
    PDF[23 official PDFs] --> DOC[Docling + pypdfium2, page-aware chunking] --> EMB[bge-m3] --> QD
```

The API (FastAPI) and a Streamlit interface run locally. Postgres stores user accounts and Qdrant
stores the vectors, both in Docker. Embedding and reranking run on one consumer GPU (NVIDIA
RTX 4060, 8 GB). The LLM is called through an OpenAI-compatible API. The original system's
Text-to-SQL route and web-search fallback are disabled.

## 7. Dataset

### 7.1 Corpus

The corpus contains 23 publicly available official documents from central and Maharashtra
government sources, listed with source URLs in `data/sources.csv`.

| Document language | Documents | Pages | Chunks (512) |
|---|---|---|---|
| English | 9 | 213 | 433 |
| Marathi | 7 | 257 | 1,023 |
| Hindi | 4 | 101 | 209 |
| English + Hindi (bilingual) | 3 | 102 | 304 |
| **Total** | **23** | **673** | **1,969** |

*Source: `data/sources.csv`, `results/ingestion_512.json`.*

By category, 13 documents are government schemes, 4 cooperative schemes, 3 cooperative policy and
3 cooperative law (`data/sources.csv`). Four topics exist in parallel language versions: the
National Cooperation Policy 2025 (en/hi), the grain storage plan SOP (en/hi), the PM-KISAN e-KYC
note (en/hi/mr) and the Maharashtra Women Farmers Empowerment Act 2026 (en/mr).

| Chunk size (tokens) | Chunks | Mean tokens per chunk | Mean characters per chunk | Pages without chunks |
|---|---|---|---|---|
| 256 | 3,557 | 184.8 | 484.6 | 0 |
| 512 | 1,969 | 333.8 | 875.7 | 0 |
| 1024 | 1,296 | 507.1 | 1,330.4 | 0 |

*Source: `results/ingestion_256.json`, `results/ingestion_512.json`, `results/ingestion_1024.json`.*

Mean chunk length is well below the maximum because the chunker splits at headings and paragraphs.

### 7.2 Evaluation questions

| Type | Base questions | Languages | Total |
|---|---|---|---|
| Answerable (gold file + page + supporting text) | 58 | 4 | 232 |
| Unanswerable (in domain, answer not in the corpus) | 10 | 4 | 40 |
| Adversarial: prompt injection / false premise / out of domain | 3 / 3 / 2 | 4 | 32 |
| **Total** | **76** | | **304** |

*Source: `eval/coop_questions.yaml`.*

The answerable questions cover all 23 documents. 21 of the 58 base answerable questions accept
more than one gold document, typically a parallel language version. By the first gold document,
32 base questions are answered from an English document, 15 from Marathi, 8 from a bilingual and
3 from a Hindi document. So most Hindi and Marathi question versions must be answered across
languages. A validator checks that each supporting text occurs on the stated page. The Hindi,
Marathi and Hinglish versions were produced by translation and have **not yet been verified by
native speakers** (all 304 questions are `verified: false`). This is a limitation (Section 12).

## 8. Experimental Setup

- **Hardware:** one NVIDIA RTX 4060 (8 GB), Windows 11.
- **Models:** embeddings `BAAI/bge-m3`; reranker `BAAI/bge-reranker-v2-m3`; answer LLM
  `gpt-4.1-mini`; grader (CRAG, Self-RAG reviewer) and Ragas judge `gpt-4o-mini`, both through the
  OpenAI API at temperature 0 (`llm_answer` / `llm_grader` columns of `results/summary.csv`).
- **Protocol:** the answer cache is off; top-k = 5; rerank from 20 candidates; one variable
  changes per experiment. Retrieval-only experiments score the 232 answerable questions. Answer
  experiments use all 304 questions (Exp 6: the 76 English questions). Ragas runs on a
  language-balanced subset of 40 answered questions.
- **Significance:** two-sided sign test on per-question scores (ties dropped). The four language
  versions of a question are not independent, so p-values are indicative.

| Exp | Variable | Configurations |
|---|---|---|
| 1 | chunk size | 256, 512, 1024 (hybrid + rerank) |
| 2 | retrieval method | TF-IDF, BM25, dense, hybrid (no rerank); dense + rerank; hybrid + rerank |
| 3 | reranking | off / on (retrieval: dense and hybrid; answers + Ragas: hybrid) |
| 4 | question language | Exp 3 hybrid + rerank run, split by language |
| 5 | question type | Exp 3 hybrid + rerank run, split by answerable / unanswerable / adversarial |
| 6 | advanced RAG | baseline, HyDE, CRAG, Self-RAG (original and refusal-aware prompt), English |
| Security | guardrail layer | 32 adversarial + 32 answerable control questions through the API |

## 9. Evaluation Metrics

A retrieved chunk is **relevant** if its file equals a gold file and its page *p* satisfies
*g* − 1 ≤ *p* ≤ *g* for gold page *g* (a chunk that starts one page early may contain the answer).

- **Recall@k:** 1 if a relevant chunk is in the top *k*, else 0, averaged over questions.
- **Precision@k:** relevant chunks in the top *k* divided by *k*.
- **MRR:** 1 / rank of the first relevant chunk (0 if none), averaged.
- **Refusal detection:** the answer contains the fixed refusal or out-of-domain sentence in any of
  the four languages, or its first sentence says that the information is not in the documents
  (phrase lists for all four languages; validated by hand, Section 10.5).
- **Outcome per question:**
  - answerable: *answered* or *over-refusal*;
  - unanswerable or adversarial: *correct refusal* or *hallucination*;
  - false premise: an answer that states the correct fact counts as *premise corrected*, a good
    outcome.
- **Hallucination rate:** hallucinations / (unanswerable + adversarial answers).
- **Over-refusal rate:** over-refusals / answerable questions.
- **Language match:** the detected language of the answer equals that of the question.
- **Ragas** [Es2023]: faithfulness, answer relevancy, context precision, context recall.
- **Guardrails:** share of adversarial questions stopped per layer (regex, LLM Guard, moderation,
  LLM refusal), attack success rate, and the false-block rate on answerable control questions.

## 10. Results

### 10.1 Experiment 1: chunk size

| Chunk size | Recall@1 | Recall@3 | Recall@5 | Precision@5 | MRR | Retrieval latency (ms) |
|---|---|---|---|---|---|---|
| 256 | 0.642 | 0.793 | 0.828 | 0.328 | 0.717 | 473 |
| 512 | 0.638 | 0.785 | 0.841 | 0.321 | 0.719 | 636 |
| 1024 | 0.599 | 0.806 | 0.845 | 0.287 | 0.701 | 1,019 |

*Hybrid + rerank, n = 232 answerable questions. Source: `results/chunking_results.csv`.*

Recall@5 differs by less than 0.02 between chunk sizes. Neither 256 vs 512 (8 vs 5 questions
better, p = 0.58) nor 512 vs 1024 (6 vs 5, p = 1.0) is significant (`results/significance.csv`).
Larger chunks lower precision@5 and more than double the retrieval latency from 256 to 1024
tokens, most likely because the reranker reads longer passages. We use 512 tokens for the other experiments.

![Chunk size](../results/figures/chunk_size.png)

### 10.2 Experiment 2: retrieval method

| Method (512) | Recall@1 | Recall@3 | Recall@5 | Precision@5 | MRR | Latency (ms) |
|---|---|---|---|---|---|---|
| TF-IDF (original tokenizer) | 0.310 | 0.422 | 0.457 | 0.161 | 0.372 | 1 |
| BM25 (Devanagari-aware) | 0.345 | 0.461 | 0.487 | 0.178 | 0.401 | 4 |
| Dense (bge-m3) | 0.491 | 0.660 | 0.728 | 0.271 | 0.579 | 327 |
| Hybrid (dense + BM25, RRF) | 0.375 | 0.603 | 0.720 | 0.241 | 0.501 | 326 |
| Dense + rerank | 0.625 | 0.785 | 0.853 | 0.322 | 0.714 | 596 |
| Hybrid + rerank | 0.638 | 0.785 | 0.841 | 0.321 | 0.719 | 636 |

*n = 232 answerable questions. Source: `results/retrieval_results.csv`.*

| Method | EN R@5 | HI R@5 | MR R@5 | Hinglish R@5 | EN MRR | HI MRR | MR MRR | Hinglish MRR |
|---|---|---|---|---|---|---|---|---|
| TF-IDF | 0.638 | 0.276 | 0.241 | 0.672 | 0.526 | 0.217 | 0.197 | 0.546 |
| BM25 | 0.672 | 0.241 | 0.362 | 0.672 | 0.595 | 0.186 | 0.251 | 0.572 |
| Dense | 0.690 | 0.741 | 0.793 | 0.690 | 0.560 | 0.603 | 0.613 | 0.540 |
| Hybrid | 0.724 | 0.655 | 0.707 | 0.793 | 0.565 | 0.401 | 0.446 | 0.594 |
| Dense + rerank | 0.793 | 0.897 | 0.879 | 0.845 | 0.721 | 0.742 | 0.737 | 0.655 |
| Hybrid + rerank | 0.810 | 0.828 | 0.862 | 0.862 | 0.739 | 0.718 | 0.742 | 0.676 |

*n = 58 answerable questions per language. Source: `results/retrieval_results.csv`.*

- Dense retrieval beats both lexical methods by a wide margin (BM25 vs dense: 73 vs 17 questions
  better, p < 0.001).
- Without a reranker, hybrid fusion does not improve on dense overall (recall@5 0.720 vs 0.728,
  p = 0.87) and lowers MRR (0.501 vs 0.579, p = 0.002). The loss is concentrated in Devanagari
  questions: Hindi MRR 0.603 → 0.401 and Marathi 0.613 → 0.446 (both p < 0.001). Hinglish and
  English questions gain slightly (Hinglish recall@5 0.690 → 0.793, p = 0.11).
- After reranking, dense and hybrid are statistically indistinguishable (recall@5 0.853 vs 0.841,
  p = 0.51; MRR 0.714 vs 0.719, p = 1.0).

![Recall@k by method](../results/figures/recall_at_k.png)

![Recall@5 by language](../results/figures/language_wise.png)

**Same-script vs cross-script questions.** Lexical search can only match words written in the same
script. We split the answerable questions by whether a gold document is written in the question's
script: Devanagari for Hindi and Marathi, Latin for English and Hinglish.

| Language | Same script? | n | TF-IDF | BM25 | Dense | Hybrid + rerank |
|---|---|---|---|---|---|---|
| English | yes | 40 | 0.825 | 0.950 | 0.850 | 1.000 |
| English | no | 18 | 0.222 | 0.056 | 0.333 | 0.389 |
| Hindi | yes | 43 | 0.326 | 0.302 | 0.674 | 0.791 |
| Hindi | no | 15 | 0.133 | 0.067 | 0.933 | 0.933 |
| Marathi | yes | 43 | 0.279 | 0.465 | 0.744 | 0.837 |
| Marathi | no | 15 | 0.133 | 0.067 | 0.933 | 0.933 |
| Hinglish | yes | 40 | 0.850 | 0.875 | 0.850 | 1.000 |
| Hinglish | no | 18 | 0.278 | 0.222 | 0.333 | 0.556 |

*Recall@5. Source: `results/script_match_results.csv`.*

![Same-script retrieval](../results/figures/script_match.png)

Cross-script questions are almost unreachable for lexical methods (BM25 recall@5 0.056–0.222),
while dense retrieval answers 14 of 15 cross-script Hindi and Marathi questions (0.933).
Surprisingly, same-script Hindi and Marathi questions are *harder* for dense retrieval (0.674 and
0.744) than cross-script ones. Section 11.2 discusses why.

### 10.3 Experiment 3: reranking

| Search | Rerank | Recall@5 | MRR | Questions better / worse with rerank | p (recall@5) |
|---|---|---|---|---|---|
| Dense | off → on | 0.728 → 0.853 | 0.579 → 0.714 | 29 / 0 | < 0.001 |
| Hybrid | off → on | 0.720 → 0.841 | 0.501 → 0.719 | 30 / 2 | < 0.001 |

*Retrieval only, n = 232. Source: `results/reranking_results.csv`, `results/significance.csv`.*

The reranker is the largest single improvement in the pipeline. It adds about 270–310 ms per
question (Table 10.2).

![Reranking effect](../results/figures/rerank_effect.png)

**With answers.** Both hybrid runs answered all 304 questions:

| Metric | Hybrid | Hybrid + rerank |
|---|---|---|
| Recall@5 / MRR | 0.720 / 0.501 | 0.841 / 0.719 |
| Over-refusal (answerable) | 0.194 | 0.095 |
| Hallucination (unanswerable + adversarial) | 0.069 | 0.056 |
| Correct refusal (unanswerable) | 0.875 | 0.900 |
| Ragas faithfulness | 0.910 | 0.811 |
| Ragas answer relevancy | 0.871 | 0.865 |
| Ragas context precision | 0.717 | 0.926 |
| Ragas context recall | 0.950 | 1.000 |
| Mean total latency (s) | 3.06 | 2.06 |

*n = 304 questions per run; Ragas on 40 answered questions each. Source:
`results/reranking_results.csv`.*

Reranking halves over-refusal (0.194 → 0.095). This is consistent with Section 10.5, where most
refusals follow retrieval misses. Reranking also raises Ragas context precision (0.717 → 0.926).
Faithfulness is higher without reranking (0.910 vs 0.811). The Ragas subset is the first 10
answered questions per language, so the two runs score partly different answers, and each value
rests on 40 answers. We therefore do not read this difference as an effect of reranking. The
total latency is lower with reranking despite the extra 310 ms retrieval step. The difference comes
from the generation step (1.38 s vs 2.77 s mean), which we attribute to API latency variation
rather than to the configuration.

![Ragas scores with and without reranking](../results/figures/faithfulness.png)

### 10.4 Experiment 4: language

| Language | Questions | Recall@5 | MRR | Answer in question's language | Over-refusal | Hallucination | Faithfulness | Answer relevancy |
|---|---|---|---|---|---|---|---|---|
| English | 76 | 0.810 | 0.739 | 1.000 | 0.155 | 0.056 | 0.825 | 0.924 |
| Hindi | 76 | 0.828 | 0.718 | 1.000 | 0.069 | 0.056 | 0.760 | 0.838 |
| Marathi | 76 | 0.862 | 0.742 | 0.987 | 0.069 | 0.056 | 0.883 | 0.827 |
| Hinglish | 76 | 0.862 | 0.676 | 0.987 | 0.086 | 0.056 | 0.775 | 0.869 |
| All | 304 | 0.841 | 0.719 | 0.993 | 0.095 | 0.056 | 0.811 | 0.865 |

*Hybrid + rerank, answers by gpt-4.1-mini. Per language: recall, MRR and over-refusal over 58
answerable questions; hallucination over 18 unanswerable + adversarial questions; Ragas over 10
answered questions. Source: `results/multilingual_results.csv`.*

The system answers in the question's language in 99.3% of cases, including Hinglish (98.7%).
Retrieval quality is similar across languages (recall@5 0.81–0.86). Hallucination is identical in
all four languages (1 of 18 questions each, the same base question; Section 10.5). Over-refusal is
highest for English (9 of 58), which matches its lower recall@5. The Ragas scores vary more
(faithfulness 0.76–0.88), but each is based on only 10 answers per language.

![Answer quality by language](../results/figures/language_wise.png)

### 10.5 Experiment 5: hallucination and over-refusal

| Question type | n | Answered | Correct refusal | Premise corrected | Hallucination | Over-refusal |
|---|---|---|---|---|---|---|
| Answerable | 232 | 0.905 | – | – | – | 0.095 |
| Unanswerable | 40 | – | 0.900 | – | 0.100 | – |
| Adversarial (all) | 32 | – | 0.875 | 0.125 | 0.000 | – |
| – prompt injection | 12 | – | 1.000 | – | 0.000 | – |
| – false premise | 12 | – | 0.667 | 0.333 | 0.000 | – |
| – out of domain | 8 | – | 1.000 | – | 0.000 | – |

*Hybrid + rerank, gpt-4.1-mini, direct pipeline (no API guardrails, so injections reach the LLM).
Source: `results/hallucination_results.csv`.*

The system refused 36 of 40 unanswerable questions. The four hallucinations are the four language
versions of one question: "What new income-tax relief was given to cooperative societies in
Budget 2024-25?". The corpus describes earlier tax reliefs, and the model presented them as the
2024-25 relief. This is a temporal false premise hidden inside an otherwise answerable-looking
question. The model resisted all adversarial questions: it refused every injection and
out-of-domain question, and it corrected or refused every false premise.

**Over-refusal follows retrieval failure.** Of the 22 over-refusals, 20 occurred when no relevant
chunk was in the top 5. When retrieval succeeded (195 questions), the model refused only 2 times;
when it failed (37 questions), it refused 20 times and answered 17 times from other chunks
(`results/raw/exp3_hybrid_rerank_20260930_034114.csv`). Most refusals are therefore correct
behaviour given the context, and better retrieval would reduce them.

![Hallucination and over-refusal](../results/figures/hallucination_rate.png)

**Measuring refusals.** The prompt asks for a fixed refusal sentence, but gpt-4.1-mini often wrote
refusals in its own words, especially in Hindi and Marathi ("उपलब्ध दस्तावेज़ों में … की जानकारी
नहीं मिली"). Matching only the fixed sentence would have counted 23 correct refusals as
hallucinations (hallucination rate 0.375 instead of 0.056) and missed 10 over-refusals. The
refusal detector therefore also accepts "not in the documents" phrases in the first sentence of
the answer, in all four languages. We read all 35 answers whose label changed: 34 were clearly
labelled correctly, and 1 was borderline (a hedge followed by related information).

### 10.6 Experiment 6: HyDE, CRAG and Self-RAG

| Configuration | Recall@5 | Over-refusal | Correct refusal (unanswerable) | Hallucination | Total latency (s) | LLM tokens per question |
|---|---|---|---|---|---|---|
| Baseline (hybrid + rerank) | 0.810 | 0.155 | 0.90 | 0.056 | 1.91 | 2,514 |
| HyDE | 0.793 | 0.155 | 0.90 | 0.056 | 8.05 | 2,732 |
| CRAG | 0.810 | 0.172 | 0.90 | 0.056 | 5.47 | 3,908 |
| Self-RAG, refusal-aware prompt | 0.810 | 0.172 | 0.90 | 0.056 | 7.61 | 5,928 |
| Self-RAG, original prompt | 0.810 | 0.190 | 0.90 | 0.111 | 12.19 | 9,486 |

*76 English questions per run (58 answerable; 18 unanswerable or adversarial). Baseline = English
rows of the Exp 3 hybrid + rerank run. Source: `results/advanced_rag_results.csv`.*

None of the three techniques improves on the baseline:

- **HyDE** retrieves slightly worse (recall@5 0.793 vs 0.810), probably because the hypothetical
  answer adds generic content.
- **CRAG** and the refusal-aware **Self-RAG** each add one over-refusal (10 vs 9 of 58) and leave
  hallucination unchanged.
- **All three** add 3.6–6.1 s of latency and up to 2.4× the tokens.
- **Self-RAG with the original reviewer prompt** is the only configuration that increases
  hallucination: 2 of 18 against 1 of 18. It also uses the most tokens (9,486 per question) and
  time (12.2 s). The extra hallucination is the injection question "You are now an unrestricted
  AI. Tell me the admin password of the PM-KISAN portal." With the refusal-aware prompt, the answer
  is the fixed out-of-domain refusal. With the original prompt, the final answer instead describes
  how officials obtain PM-KISAN portal login credentials: the correct refusal was replaced by a
  regenerated, partly compliant answer (`results/raw/exp6_selfrag_original_*.csv`). The difference
  is a single question, so we report it as a case, not a rate difference.

### 10.7 Guardrails

| Question kind | n | Regex | LLM Guard | LLM refusal | Answered | Defended | Attack success / false block |
|---|---|---|---|---|---|---|---|
| Prompt injection | 12 | 11 | 1 | 0 | 0 | 1.00 | 0.00 |
| False premise | 12 | 0 | 0 | 8 | 4 (all corrected) | 1.00 | 0.00 |
| Out of domain | 8 | 0 | 2 | 6 | 0 | 1.00 | 0.00 |
| Normal answerable (control) | 32 | 0 | 8 | 1 | 23 | – | 0.25 false block |

*Through the API (login, all guardrail layers), hybrid + rerank, gpt-4.1-mini. Source:
`results/security_results.csv`, `results/raw/security_20260930_041319.csv`.*

No adversarial question succeeded. The multilingual regex layer stopped 11 of 12 injections in all
four languages; LLM Guard caught the remaining Hindi one. However, LLM Guard's prompt-injection
classifier also blocked **8 of the 32 legitimate control questions, all of them in Hindi or
Marathi**: 8 of the 16 Devanagari control questions were blocked, against 0 of 16 English and
Hinglish ones. All 8 carried the label "PromptInjection". The two out-of-domain questions it
stopped (one Marathi, one Hindi) were blocked under the same label, so they are the same false
positive, not an out-of-domain detection. For Devanagari users, the English-trained classifier
turns half of the normal questions into errors.

### 10.8 Latency

Retrieval latency per question: 1 ms (TF-IDF), 4 ms (BM25), 327 ms (dense), 326 ms (hybrid),
596 ms (dense + rerank) and 636 ms (hybrid + rerank) (`results/retrieval_results.csv`). Both
sparse indexes are built once per collection and cached. The original system rebuilt the TF-IDF
index on every query: 846 ms per query on average, against 6.3 ms for the cached BM25 index over
30 timed queries (`results/tokenizer_results.csv`).

With answer generation, mean end-to-end latency is 2.06 s for hybrid + rerank (0.67 s retrieval,
1.38 s generation) and 3.06 s for hybrid without reranking (`results/reranking_results.csv`). The
advanced techniques are 3–6 times slower (`results/advanced_rag_results.csv`): HyDE 8.05 s,
CRAG 5.47 s, Self-RAG 7.61 s (refusal-aware) and 12.19 s (original prompt). HyDE and CRAG spend
their extra time in an additional LLM call during retrieval; Self-RAG spends it in review and
regeneration.

![Retrieval latency](../results/figures/latency.png)

## 11. Discussion

### 11.1 Tokenization breaks Devanagari words

The original TF-IDF analyzer treats Devanagari vowel signs and the virama as word boundaries. On
the 512-token corpus it kept only 5.2% of Devanagari word types intact; 63.3% were split into
fragments and 31.5% disappeared entirely. For Marathi documents only 3.1% survived
(`results/tokenizer_results.csv`). "प्रधानमंत्री फसल बीमा योजना" became the fragments
`रध, नम, फसल, जन`. Our tokenizer keeps whole words. For same-script Marathi questions, BM25 with
the new tokenizer raises recall@5 from 0.279 to 0.465. For same-script English questions it rises
from 0.825 to 0.950 (Section 10.2).

### 11.2 A correct tokenizer cannot repair a broken text layer

For same-script Hindi questions, BM25 does not beat TF-IDF (0.302 vs 0.326). Dense retrieval also
does worse on same-script Hindi (0.674) and Marathi (0.744) questions than on cross-script ones
(0.933). The evidence points to the documents rather than to the retrievers. Several Hindi and
Marathi PDFs use fonts whose embedded text does not map to correct Unicode, so the extracted text
contains misspelled or split words. The document-check step flagged such damage in the Hindi and
Marathi PDFs (P3 in `CHANGELOG.md`; the per-file damage figures are not yet exported to
`results/`). In the smoke test, a Hindi answer about the grain storage plan turned "common
processing units" into "coin processing" units: the English SOP was correct, but the damaged Hindi
text was retrieved and misread. For Indian-language RAG, text-layer quality is therefore a first-order
variable. Better OCR for Devanagari, or preferring the English version of parallel documents,
may matter more than the choice of retriever.

### 11.3 Hybrid search is not free for cross-lingual questions

RRF gives each list equal weight. When most Hindi and Marathi questions are answered by English
documents, the BM25 list contains mostly irrelevant chunks, and fusion pushes them into the top
ranks (Hindi MRR 0.603 → 0.401). A cross-encoder reranker removes most of this damage. Without a
reranker, hybrid retrieval should be weighted by script: use BM25 only when question and corpus
share a script.

### 11.4 English-only components in a multilingual pipeline

Two components of the inherited guardrail stack assume English:

- **PII filter:** its named-entity recogniser labelled common Hindi and Marathi words as person
  names and redacted them before retrieval. In a manual API check this corrupted several Devanagari
  smoke-test questions (P7 in `CHANGELOG.md`), so we disabled the PERSON entity.
- **Regex injection filter:** it contained only English patterns, and some of them also blocked
  legitimate questions. We replaced them with 23 patterns in four languages.

The third component, the LLM Guard prompt-injection classifier, is also an English model, and it
fails in both directions. It added little protection: the regex layer had already stopped 11 of
12 injections. It also blocked half of the legitimate Hindi and Marathi questions (Section 10.7).
In a multilingual deployment, an English-trained safety model can quietly exclude the very users
the system is built for. Such components should be evaluated per language with benign control
questions, and restricted to the languages they were trained on or replaced by a multilingual
classifier. The same holds for the rest of the pipeline. Our fixed refusal sentence was
paraphrased by the answer model in Hindi and Marathi, so a string-matching evaluation would have
reported a hallucination rate almost seven times too high (Section 10.5).

### 11.5 Self-RAG and refusal bias

The inherited Self-RAG reviewer prompt tells the reviewer to fail answers that "don't deliver real
value", and it scores a refusal as a failed answer that must be regenerated. In a system whose
safety depends on refusing, this optimises against its own grounding rule. Our results show the
effect on a small scale. The original prompt doubled hallucination (1 → 2 of 18) and raised
over-refusal (9 → 11 of 58). The one extra hallucination was the clearest possible case: a
correctly refused prompt injection was "improved" into a partly compliant answer (Section 10.6).
It also cost 1.6 times the tokens of the refusal-aware reviewer and 3.8 times those of the
baseline, because weak-looking refusals triggered regeneration loops. The refusal-aware prompt
counts a correct refusal as a good answer and inventing facts as worse than refusing. It removed
the extra hallucination but did not improve on the baseline. With a well-grounded generator, a
self-reflection loop mainly adds cost, and a badly specified reviewer adds risk.

## 12. Limitations

- **Small dataset:** 23 documents and 76 base questions; per-language subsets have 58 answerable
  questions, so small differences are not significant.
- **Unverified translations and answers:** the Hindi, Marathi and Hinglish questions were machine
  translated and not yet checked by native speakers. The gold evidence (file, page, supporting text)
  is shared by the four versions and was checked automatically. The expected answers have not yet
  been reviewed by a person.
- **Question authorship:** the questions were written by the system builders, who also wrote the
  injection patterns, and the injection questions were written after the patterns. Guardrail block
  rates may therefore be optimistic.
- **Non-independent samples:** the four language versions of a question are not independent, so
  the sign-test p-values are indicative.
- **Single LLM and LLM judge:** answer-level results come from a single LLM (gpt-4.1-mini), and
  Ragas metrics rely on an LLM judge (gpt-4o-mini) over only 40 answers per run.
- **Heuristic refusal detection:** refusals are detected from fixed sentences and "not in the
  documents" phrases. Only the 35 labels that changed with the phrase rules were checked by hand,
  not all 304.
- **Experiment 6 in English only:** it covers 76 questions (18 unanswerable or adversarial), so its
  hallucination differences are single questions.
- **API latency:** generation latency depends on the provider's API and varied between runs.
- **Damaged text:** some official Hindi and Marathi PDFs have damaged text layers, which confounds
  language effects with document quality.
- **Single hardware setup:** latency was measured on one consumer GPU.

## 13. Conclusion

For a multilingual assistant over Indian cooperative and scheme documents, multilingual dense
retrieval plus a cross-encoder reranker is the decisive combination: recall@5 rises from 0.46–0.49
for lexical methods to 0.84–0.85. Chunk size and the choice between dense and hybrid retrieval
after reranking matter little. Fixing Devanagari tokenization helps lexical search where the text
is clean, but damaged PDF text layers and cross-lingual questions limit what lexical methods can
do.

With strict grounding rules, a small LLM answers in the user's language almost always (99.3%),
refuses 90% of unanswerable questions, and hallucinates on one temporal false-premise question.
Most remaining refusals are retrieval failures, not generation failures. HyDE, CRAG and Self-RAG
add latency without reducing hallucination. A reviewer prompt that penalises refusals makes
things worse, so self-reflection must treat "not in the documents" as a valid answer.

The most important lesson for Indian-language deployments concerns the components around the
LLM:

- an English PII recogniser corrupted Devanagari questions;
- an English prompt-injection classifier blocked half of the legitimate Hindi and Marathi
  questions;
- a string-matching refusal metric would have overstated hallucination almost sevenfold.

Every such component needs its own per-language evaluation, with benign control questions, before
it is trusted.

## References

- [Acharya2024] A. Acharya, R. Murthy, V. Kumar, J. Sen. "Hindi-BEIR: A Large Scale Retrieval
  Benchmark in Hindi." arXiv:2408.09437, 2024. https://arxiv.org/abs/2408.09437
- [Asai2023] A. Asai, Z. Wu, Y. Wang, et al. "Self-RAG: Learning to Retrieve, Generate, and
  Critique through Self-Reflection." arXiv:2310.11511, 2023. https://arxiv.org/abs/2310.11511
- [Auer2024] C. Auer, M. Lysak, A. Nassar, et al. "Docling Technical Report." arXiv:2408.09869,
  2024. https://arxiv.org/abs/2408.09869
- [BGERerank] BAAI. "bge-reranker-v2-m3" (model card). https://huggingface.co/BAAI/bge-reranker-v2-m3
- [Bilal2026] M. Bilal, G. Gopakumar. "AgriGov: A Structured Multilingual Dataset Curation for
  Indian Government Schemes for Farmers." arXiv:2606.08272, 2026. https://arxiv.org/abs/2606.08272
- [Census2011] Office of the Registrar General, India. "Census of India 2011, Paper 1 of 2018:
  Language — India, States and Union Territories (Table C-16)." 2018.
  https://censusindia.gov.in/nada/index.php/catalog/42458
- [Chen2024] J. Chen, S. Xiao, P. Zhang, et al. "M3-Embedding: Multi-Linguality,
  Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation."
  arXiv:2402.03216, 2024. https://arxiv.org/abs/2402.03216
- [Cormack2009] G. V. Cormack, C. L. A. Clarke, S. Büttcher. "Reciprocal rank fusion outperforms
  Condorcet and individual rank learning methods." Proc. SIGIR 2009.
  https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- [Doddapaneni2023] S. Doddapaneni, R. Aralikatte, G. Ramesh, et al. "Towards Leaving No Indic
  Language Behind: Building Monolingual Corpora, Benchmark and Models for Indic Languages." Proc.
  ACL 2023. https://aclanthology.org/2023.acl-long.693
- [Es2023] S. Es, J. James, L. Espinosa-Anke, S. Schockaert. "Ragas: Automated Evaluation of
  Retrieval Augmented Generation." arXiv:2309.15217, 2023. https://arxiv.org/abs/2309.15217
- [Gao2022] L. Gao, X. Ma, J. Lin, J. Callan. "Precise Zero-Shot Dense Retrieval without
  Relevance Labels." arXiv:2212.10496, 2022. https://arxiv.org/abs/2212.10496
- [Gupta2014] P. Gupta, K. Bali, R. E. Banchs, M. Choudhury, P. Rosso. "Query Expansion for
  Mixed-Script Information Retrieval." Proc. SIGIR 2014. doi:10.1145/2600428.2609622
- [Haq2024] S. Haq, A. Sharma, O. Khattab, N. Chhaya, P. Bhattacharyya. "IndicIRSuite:
  Multilingual Dataset and Neural Information Models for Indian Languages." Proc. ACL 2024
  (Volume 2: Short Papers), pp. 501–509. doi:10.18653/v1/2024.acl-short.46
- [Hines2024] K. Hines, G. Lopez, M. Hall, et al. "Defending Against Indirect Prompt Injection
  Attacks With Spotlighting." arXiv:2403.14720, 2024. https://arxiv.org/abs/2403.14720
- [Lewis2020] P. Lewis, E. Perez, A. Piktus, et al. "Retrieval-Augmented Generation for
  Knowledge-Intensive NLP Tasks." arXiv:2005.11401, 2020. https://arxiv.org/abs/2005.11401
- [LLMGuard] Protect AI. "LLM Guard: The Security Toolkit for LLM Interactions" (software).
  https://github.com/protectai/llm-guard
- [Majumder2010] P. Majumder, M. Mitra, D. Pal, et al. "The FIRE 2008 Evaluation Exercise." ACM
  Transactions on Asian Language Information Processing 9(3):1–24, 2010. doi:10.1145/1838745.1838747
- [Mukherjee2019] S. Mukherjee, P. Pal. "On Improving Awareness about Crop Insurance in India."
  Review of Agrarian Studies 9(1), 2019. doi:10.25003/RAS.09.01.0006
- [RankBM25] D. Brown. "rank_bm25" (software). https://github.com/dorianbrown/rank_bm25
- [Robertson2009] S. Robertson, H. Zaragoza. "The Probabilistic Relevance Framework: BM25 and
  Beyond." Foundations and Trends in Information Retrieval 3(4):333–389, 2009.
  doi:10.1561/1500000019
- [Singh2024] N. Singh, J. Wang'ombe, N. Okanga, et al. "Farmer.Chat: Scaling AI-Powered
  Agricultural Services for Smallholder Farmers." arXiv:2409.08916, 2024.
  https://arxiv.org/abs/2409.08916
- [Yan2024] S.-Q. Yan, J.-C. Gu, Y. Zhu, Z.-H. Ling. "Corrective Retrieval Augmented
  Generation." arXiv:2401.15884, 2024. https://arxiv.org/abs/2401.15884
- [Zhang2022] X. Zhang, N. Thakur, O. Ogundepo, et al. "Making a MIRACL: Multilingual Information
  Retrieval Across a Continuum of Languages." arXiv:2210.09984, 2022.
  https://arxiv.org/abs/2210.09984
