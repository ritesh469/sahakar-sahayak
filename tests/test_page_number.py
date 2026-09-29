"""P2: page_number survives PDF -> chunker -> seed_db ingest -> Qdrant payload -> search results."""

import random
import uuid
from functools import partial
from types import SimpleNamespace

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.config import settings
from app.models import RetrievedChunk
from app.services import vector_store
from app.services.document_processor import DocumentProcessor, _page_number

PAGES = {
    1: [
        "Pradhan Mantri Fasal Bima Yojana provides crop insurance to farmers.",
        "Farmers pay a low premium and the government pays the remaining share.",
        "The scheme covers losses from drought, flood, pests and natural disasters.",
        "Claims are settled directly into the bank account of the farmer.",
        "All food crops, oilseeds and annual horticultural crops are covered.",
    ],
    2: [
        "A primary agricultural credit society is registered under the state cooperative act.",
        "Every member has one vote in the general body meeting of the society.",
        "The managing committee is elected by members for a term of five years.",
        "The registrar of cooperative societies audits the accounts every year.",
        "Members may borrow short term crop loans at a concessional interest rate.",
    ],
}


def _make_pdf(path):
    pdf = canvas.Canvas(str(path), pagesize=A4)
    for lines in PAGES.values():
        y = 780
        for line in lines:
            pdf.drawString(50, y, line)
            y -= 40
        pdf.showPage()
    pdf.save()


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic vectors so the test does not need the GPU embedding model."""
    return [
        [random.Random(t).uniform(-1, 1) for _ in range(settings.embedding_dim)] for t in texts
    ]


@pytest.fixture(scope="module", autouse=True)
def isolated_doc_cache(tmp_path_factory):
    """Keep test conversions out of the real DOC_CACHE_DIR."""
    old = settings.doc_cache_dir
    settings.doc_cache_dir = str(tmp_path_factory.mktemp("doc_cache"))
    yield
    settings.doc_cache_dir = old


@pytest.fixture(scope="module")
def pdf_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("docs") / "two_pages.pdf"
    _make_pdf(path)
    return path


@pytest.fixture(scope="module")
def processor():
    # Small chunks so each page produces chunks of its own
    return DocumentProcessor(chunk_size=48, chunk_overlap=0)


@pytest.fixture(scope="module")
def chunks(processor, pdf_path):
    return processor.process_document(str(pdf_path))


def test_every_chunk_has_page_number(chunks):
    assert chunks
    assert all(isinstance(c["page_number"], int) for c in chunks)
    assert all(len(c["text"].strip()) >= 10 for c in chunks)  # no empty/near-empty chunks
    assert {c["page_number"] for c in chunks} == {1, 2}


def test_page_number_matches_page_text(chunks):
    for c in chunks:
        if "Fasal" in c["text"]:
            assert c["page_number"] == 1
        if "registrar" in c["text"]:
            assert c["page_number"] == 2


def test_page_number_for_paragraph_spanning_pages():
    # One doc item spread over pages 1-3; the chunker cuts it into pieces
    item_text = "alpha " * 20 + "beta " * 20 + "gamma " * 20
    prov = [
        SimpleNamespace(page_no=1, charspan=(0, 119)),
        SimpleNamespace(page_no=2, charspan=(120, 219)),
        SimpleNamespace(page_no=3, charspan=(220, len(item_text))),
    ]
    item = SimpleNamespace(text=item_text, prov=prov)

    def chunk(text):
        return SimpleNamespace(text=text, meta=SimpleNamespace(doc_items=[item]))

    assert _page_number(chunk("alpha alpha")) == 1
    assert _page_number(chunk("beta beta beta")) == 2
    assert _page_number(chunk("gamma gamma\nnext item")) == 3
    assert _page_number(chunk("text not in item")) == 1  # fallback: first page of the item
    no_pages = SimpleNamespace(text="x", meta=SimpleNamespace(doc_items=[SimpleNamespace(prov=[])]))
    assert _page_number(no_pages) is None  # DOCX/HTML/TXT


def test_chunks_respect_chunk_size(processor, chunks):
    assert all(processor.tokenizer.count_tokens(c["text"]) <= 48 for c in chunks)


def test_chunk_overlap_prepends_previous_tail(pdf_path, chunks):
    # 64 - 16 = 48, so the base chunks are identical to the chunk_size=48 ones
    overlapped = DocumentProcessor(chunk_size=64, chunk_overlap=16).process_document(str(pdf_path))
    assert len(overlapped) == len(chunks) > 1
    assert overlapped[0]["text"] == chunks[0]["text"]
    for i in range(1, len(chunks)):
        assert overlapped[i]["text"].endswith(chunks[i]["text"])
        prefix = overlapped[i]["text"][: -len(chunks[i]["text"])].strip()
        assert prefix and prefix.split()[-1] in chunks[i - 1]["text"]
        assert overlapped[i]["page_number"] == chunks[i]["page_number"]


def test_collection_name_uses_prefix_and_chunk_size():
    assert vector_store.collection_name(256) == f"{settings.qdrant_collection_prefix}_256"
    assert vector_store.collection_name() == (
        f"{settings.qdrant_collection_prefix}_{settings.chunk_size}"
    )


def test_ingest_saves_page_number_in_qdrant(processor, pdf_path):
    from scripts.seed_db import _ingest_one

    client = vector_store.get_client()
    try:
        client.get_collections()
    except Exception:  # noqa: BLE001
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url}")

    collection = f"test_p2_{uuid.uuid4().hex[:8]}"
    upsert = partial(vector_store.upsert_chunks, collection=collection)
    counters = {"true_ingested": 0, "noisy_ingested": 0, "failed": 0, "chunks": 0}
    try:
        _ingest_one(processor, pdf_path, 1, 1, counters, _fake_embed, upsert, RetrievedChunk)
        assert counters["failed"] == 0
        assert counters["chunks"] > 0

        points, _ = client.scroll(collection, limit=1000, with_payload=True)
        assert len(points) == counters["chunks"]
        assert {p.payload["page_number"] for p in points} == {1, 2}

        query = _fake_embed(["crop insurance"])[0]
        results = vector_store.search(query, top_k=1000, collection=collection)
        assert len(results) == len(points)
        assert {r.page_number for r in results} == {1, 2}

        # Per-document record for the ingestion report
        record = counters["documents"][0]
        assert record["status"] == "ok" and record["chunks"] == len(points)
        assert record["pages"] == 2 and record["chunks_with_page"] == len(points)

        # Deterministic ids: ingesting the same file again must not duplicate points;
        # the second run reads the conversion from the doc cache
        _ingest_one(processor, pdf_path, 1, 1, counters, _fake_embed, upsert, RetrievedChunk)
        assert client.count(collection).count == len(points)
        assert processor.last_info["cached"] is True
    finally:
        if client.collection_exists(collection):
            client.delete_collection(collection)
