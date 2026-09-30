import argparse
import os
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from loguru import logger

from app.config import settings
from app.middleware.auth import hash_password



# From .env via app.config (an exported DATABASE_URL still wins), so the script uses the same
# Postgres as the API (port 5434) instead of a hardcoded default that points at another DB.
DATABASE_URL = settings.database_url
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "seed", "migrations")
# 003 is the old K8s SQL demo: it starts with DROP TABLE ... CASCADE, so it never runs here.
SKIP_MIGRATIONS = {"003_seed_k8s_ops.sql"}
DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "seed", "docs")

DEMO_USERS = [
    ("agent@demo.local", "agent123", False),
    ("admin@demo.local", "admin123", True),
]

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
SAMPLE_SEED = 42



def _collect_files(subdir: str) -> list[Path]:
    root = Path(DOCS_DIR) / subdir
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and p.name != ".gitkeep"
    )

def _select_corpus(noise_sample_size: int | str) -> tuple[list[Path], list[Path]]:
    true_files = _collect_files("true_data")
    all_noisy = _collect_files("noisy_data")

    legacy_files = [
        p for p in Path(DOCS_DIR).iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and p.name not in {".gitkeep", "README.md"}  # README documents the folder, not the corpus
    ]

    if legacy_files:
        logger.info("Found {} legacy top-level docs (treating as true signal)", len(legacy_files))

    true_files = legacy_files + true_files

    if noise_sample_size == "all":
        noisy_files = all_noisy
    else:
        n = int(noise_sample_size)
        if n <= 0 or n >= len(all_noisy):
            noisy_files = all_noisy if n > 0 else []

        else: 
            rng = random.Random(SAMPLE_SEED)
            noisy_files = rng.sample(all_noisy, n)
            noisy_files.sort()
    return true_files, noisy_files


def seed_docs(
    noise_sample_size: int | str = 150,
    chunk_size: int | None = None,
    recreate: bool = False,
    report: str | None = None,
) -> dict:
    from functools import partial

    from app.models import RetrievedChunk
    from app.services.document_processor import DocumentProcessor
    from app.services.embedding_service import embed_texts
    from app.services.vector_store import collection_name, recreate_collection, upsert_chunks

    processor = DocumentProcessor(chunk_size=chunk_size)
    collection = collection_name(processor.chunk_size)
    if recreate:
        logger.info("--recreate set; dropping and recreating collection {}", collection)
        recreate_collection(collection)
    upsert_to_collection = partial(upsert_chunks, collection=collection)
    true_files, noisy_files = _select_corpus(noise_sample_size)
    total = len(true_files) + len(noisy_files)

    logger.info("=" * 60)
    logger.info("INGESTION PLAN")
    logger.info("  collection : {} (chunk_size={}, overlap={})",
                collection, processor.chunk_size, processor.chunk_overlap)
    logger.info("  true_data  : {} files (full signal)", len(true_files))
    logger.info("  noisy_data : {} files (sample={})", len(noisy_files), noise_sample_size)
    logger.info("  total      : {} files", total)
    logger.info("=" * 60)

    
    if total == 0:
        logger.warning("No files found to ingest — did you run `make seed-data`?")
        return {"true_ingested": 0, "noisy_ingested": 0, "failed": 0, "chunks": 0}

    counters = {"true_ingested": 0, "noisy_ingested": 0, "failed": 0, "chunks": 0}
    t0 = time.time()


    for idx, src in enumerate(true_files, start=1):
        _ingest_one(processor, src, idx, total, counters, embed_texts, upsert_to_collection, RetrievedChunk)
        if counters["chunks"] > 0 and idx == len(true_files):
            logger.info("✓ All {} true (signal) files done", len(true_files))

    for jdx, src in enumerate(noisy_files, start=1):
        idx = len(true_files) + jdx
        _ingest_one(processor, src, idx, total, counters, embed_texts, upsert_to_collection, RetrievedChunk)

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("INGESTION COMPLETE in {:.1f} min", elapsed / 60)
    logger.info("  true_data ingested  : {}", counters["true_ingested"])
    logger.info("  noisy_data ingested : {}", counters["noisy_ingested"])
    logger.info("  failed (skipped)    : {}", counters["failed"])
    logger.info("  total chunks upserted: {}", counters["chunks"])
    logger.info("=" * 60)

    if report:
        write_report(report, counters, processor, collection, elapsed)
    return counters


def _source_languages() -> dict[str, str]:
    path = Path(DOCS_DIR).parent.parent / "data" / "sources.csv"
    if not path.exists():
        return {}
    import csv

    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["filename"]: r.get("language", "") for r in csv.DictReader(f)}


def write_report(path: str, counters: dict, processor, collection: str, elapsed: float) -> None:
    """Ingestion numbers for the paper (P4): documents, chunks, lengths, failures + reasons."""
    import json
    from datetime import datetime

    from app.config import settings

    docs = counters.get("documents", [])
    ok = [d for d in docs if d["status"] == "ok"]
    n_chunks = sum(d["chunks"] for d in ok)
    langs = _source_languages()
    by_lang: dict[str, dict] = {}
    for d in docs:
        d["language"] = langs.get(d["file"], "")
        agg = by_lang.setdefault(d["language"] or "unknown", {"documents": 0, "chunks": 0, "pages": 0})
        agg["documents"] += d["status"] == "ok"
        agg["chunks"] += d["chunks"]
        agg["pages"] += d.get("pages") or 0

    report = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "collection": collection,
        "chunk_size": processor.chunk_size,
        "chunk_overlap": processor.chunk_overlap,
        "embedding_model": settings.embedding_model,
        "pdf_backend": settings.pdf_backend,
        "documents_total": len(docs),
        "documents_ingested": len(ok),
        "documents_failed": len(docs) - len(ok),
        "chunks": n_chunks,
        "avg_chunks_per_document": round(n_chunks / len(ok), 1) if ok else 0,
        "avg_chunk_chars": round(sum(d["chunk_chars_total"] for d in ok) / n_chunks, 1) if n_chunks else 0,
        "avg_chunk_tokens": round(sum(d["chunk_tokens_total"] for d in ok) / n_chunks, 1) if n_chunks else 0,
        "min_chunk_tokens": min((d["chunk_tokens_min"] for d in ok), default=0),
        "max_chunk_tokens": max((d["chunk_tokens_max"] for d in ok), default=0),
        "chunks_with_page_number": sum(d["chunks_with_page"] for d in ok),
        "pages_total": sum(d.get("pages") or 0 for d in docs),
        "pages_missing": sum(len(d.get("missing_pages") or []) for d in docs),
        "by_language": by_lang,
        "failed": [{"file": d["file"], "reason": d.get("error", d["status"])}
                   for d in docs if d["status"] != "ok"],
        "elapsed_min": round(elapsed / 60, 1),
        "per_document": docs,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Ingestion report written to {}", path)


def _ingest_one(processor, src: Path, idx: int, total: int, counters: dict,
                embed_texts_fn, upsert_chunks_fn, RetrievedChunk) -> None:
    label = "true" if "true_data" in str(src) else "noisy"
    logger.info("[{}/{}] start {} {}", idx, total, label, src.name)
    record: dict = {"file": src.name, "label": label, "status": "failed", "chunks": 0}
    counters.setdefault("documents", []).append(record)
    t0 = time.time()
    try:
        chunks_meta = processor.process_document(str(src))
        info = getattr(processor, "last_info", {}) or {}
        record.update({
            "pages": info.get("pages"),
            "conversion": info.get("status"),
            "missing_pages": info.get("missing_pages", []),
        })
        if not chunks_meta:
            logger.warning("[{}/{}] {} {} → 0 chunks (skipped)", idx, total, label, src.name)
            record.update(status="empty", error="0 chunks: no extractable text")
            counters["failed"] += 1
            return
        chunks = [
            RetrievedChunk(text=c["text"], source=c["source"], page_number=c.get("page_number"))
            for c in chunks_meta
        ]
        texts = [c.text for c in chunks]
        embeddings = embed_texts_fn(texts)
        upsert_chunks_fn(chunks, embeddings)
        counters["chunks"] += len(chunks)
        counters[f"{label}_ingested"] += 1
        tokenizer = getattr(processor, "tokenizer", None)
        tokens = [tokenizer.count_tokens(t) for t in texts] if tokenizer else []
        record.update({
            "status": "ok",
            "chunks": len(chunks),
            "chunk_chars_total": sum(len(t) for t in texts),
            "chunk_tokens_total": sum(tokens),
            "chunk_tokens_min": min(tokens, default=0),
            "chunk_tokens_max": max(tokens, default=0),
            "chunks_with_page": sum(1 for c in chunks if c.page_number is not None),
        })
        if idx % 10 == 0 or idx == total:
            logger.info("  [{}/{}] progress — {} chunks so far",idx, total, counters["chunks"])

    except Exception as exc:  # noqa: BLE001
        logger.warning("[{}/{}] FAILED {} {}: {}: {}", idx, total, label, src.name,
                       type(exc).__name__, exc)
        record["error"] = f"{type(exc).__name__}: {exc}"
        counters["failed"] += 1
    finally:
        record["seconds"] = round(time.time() - t0, 1)


def run_migrations(conn: psycopg2.extensions.connection) -> None:
    cur = conn.cursor()
    files = sorted([f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")])
    for filename in files:
        if filename in SKIP_MIGRATIONS:
            logger.info("Skipping migration: {} (K8s SQL demo)", filename)
            continue
        path = os.path.join(MIGRATIONS_DIR, filename)
        with open(path) as f:
            sql = f.read()
        logger.info("Running migration: {}", filename)
        cur.execute(sql)
    conn.commit()
    cur.close()

def seed_users(conn: psycopg2.extensions.connection) -> None:
    cur = conn.cursor()
    for username, password, is_admin in DEMO_USERS:
        password_hash = hash_password(password)
        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (%s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                is_admin = EXCLUDED.is_admin
            """,
            (username, password_hash, is_admin),
        )
        logger.info("Seeded user: {} (admin={})", username, is_admin)
    conn.commit()
    cur.close()

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed DB + ingest documents")
    parser.add_argument(
        "--no-ingest", action="store_true",
        help="Run migrations + users only; skip vector-store ingestion",
    )
    parser.add_argument(
        "--ingest-only", action="store_true",
        help="Skip Postgres (migrations + users); only ingest documents into Qdrant",
    )
    parser.add_argument(
        "--noise-sample", default="150",
        help="Number of noisy docs to sample (default 150). Use 0 or 'all'.",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=None,
        help="Chunk size in tokens (default CHUNK_SIZE from .env); collection = <prefix>_<size>",
    )
    parser.add_argument(
        "--recreate", action="store_true",
        help="Drop and recreate the target Qdrant collection before ingesting",
    )
    parser.add_argument(
        "--report", default=None,
        help="Write ingestion stats JSON here, e.g. results/ingestion_512.json",
    )
    args = parser.parse_args()
    if args.no_ingest and args.ingest_only:
        raise SystemExit("--no-ingest and --ingest-only cannot be used together")

    if args.ingest_only:
        logger.info("--ingest-only set; skipping migrations + users.")
    else:
        db = urlparse(DATABASE_URL)
        logger.info("Connecting to database {}:{}{} ...", db.hostname, db.port, db.path)
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("Running migrations...")
        run_migrations(conn)
        logger.info("Seeding demo users...")
        seed_users(conn)
        conn.close()
        logger.info("DB seeding done.")

    if args.no_ingest:
        logger.info("--no-ingest set; skipping doc ingestion.")
        return

    # Parse noise-sample arg (int or 'all')
    noise_arg: int | str = args.noise_sample
    if noise_arg != "all":
        try:
            noise_arg = int(noise_arg)
        except ValueError:
            raise SystemExit(f"--noise-sample must be int or 'all', got {noise_arg!r}")

    seed_docs(noise_sample_size=noise_arg, chunk_size=args.chunk_size, recreate=args.recreate,
              report=args.report)

if __name__ == "__main__":
    main()