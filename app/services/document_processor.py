from pathlib import Path

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.chunking import HybridChunker
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from loguru import logger

from app.config import settings


def _build_tokenizer(max_tokens: int):
    """Chunk tokens are counted with the embedding model's own tokenizer.

    Docling's default (English all-MiniLM-L6-v2) miscounts Devanagari text, so a
    "512-token" chunk would not be 512 tokens for the model that embeds it.
    """
    if settings.embedding_backend == "openai":
        import tiktoken
        from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer

        return OpenAITokenizer(
            tokenizer=tiktoken.encoding_for_model(settings.embedding_model),
            max_tokens=max_tokens,
        )
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

    return HuggingFaceTokenizer.from_pretrained(settings.embedding_model, max_tokens=max_tokens)


def _page_number(chunk, delim: str = "\n") -> int | None:
    """Page on which the chunk starts; None for formats without pages (DOCX/HTML/TXT).

    A long paragraph can span pages: its prov then has one entry per page, each with a
    charspan into item.text. The chunker splits such an item into several chunks, so we
    find where this chunk starts inside the item text and pick the matching page.
    """
    for item in getattr(getattr(chunk, "meta", None), "doc_items", None) or []:
        provs = getattr(item, "prov", None) or []
        if not provs:
            continue
        if len({p.page_no for p in provs}) > 1 and getattr(item, "text", None):
            head = chunk.text.split(delim)[0][:60]
            pos = item.text.find(head) if head else -1
            for p in provs:
                if pos >= 0 and p.charspan[0] <= pos <= p.charspan[1]:
                    return p.page_no
        return min(p.page_no for p in provs)
    return None


class DocumentProcessor:
    def __init__(self, chunk_size: int | None = None, chunk_overlap: int | None = None):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError(
                f"CHUNK_OVERLAP ({self.chunk_overlap}) must be >= 0 and < CHUNK_SIZE ({self.chunk_size})"
            )

        pipeline_options = PdfPipelineOptions()
        pipeline_options.accelerator_options = AcceleratorOptions(
            num_threads=8, device=AcceleratorDevice.AUTO
        )
        if settings.pdf_backend == "pypdfium2":
            pdf_format = PdfFormatOption(
                pipeline_options=pipeline_options, backend=PyPdfiumDocumentBackend
            )
        elif settings.pdf_backend == "docling_parse":
            pdf_format = PdfFormatOption(pipeline_options=pipeline_options)
        else:
            raise ValueError(f"PDF_BACKEND must be pypdfium2 or docling_parse, got {settings.pdf_backend!r}")
        self.converter = DocumentConverter(format_options={InputFormat.PDF: pdf_format})
        # HybridChunker has no overlap option: chunk to (size - overlap) and prepend the
        # previous chunk's tail ourselves, so the final chunk stays within chunk_size.
        self.tokenizer = _build_tokenizer(self.chunk_size - self.chunk_overlap)
        self.chunker = HybridChunker(tokenizer=self.tokenizer)

    def _tail(self, text: str, n_tokens: int) -> str:
        """Last n_tokens of text, decoded back to a string."""
        tok = self.tokenizer.get_tokenizer()
        if settings.embedding_backend == "openai":
            return tok.decode(tok.encode(text)[-n_tokens:])
        return tok.convert_tokens_to_string(tok.tokenize(text)[-n_tokens:])

    def process_document(self, file_path: str) -> list[dict]:
        result = self.converter.convert(file_path)
        doc = result.document
        source_name = Path(file_path).name
        if result.status != ConversionStatus.SUCCESS:
            # Docling keeps going when single pages fail, so make lost pages visible
            converted = {p.page_no for p in result.pages}
            missing = [n for n in range(1, doc.num_pages() + 1) if n not in converted]
            logger.warning("{}: conversion {} — pages missing: {} ({} errors)",
                           source_name, result.status.value, missing, len(result.errors))
        chunk_iter = self.chunker.chunk(doc)

        chunks = []
        prev_text = ""

        for chunk in chunk_iter:
            text = chunk.text
            if self.chunk_overlap and prev_text:
                text = f"{self._tail(prev_text, self.chunk_overlap).strip()} {text}"
            prev_text = chunk.text
            chunks.append({
                "text": text,
                "source": source_name,
                "page_number": _page_number(chunk, self.chunker.delim),
            })
        logger.info("Processed {} chunks from {} (chunk_size={}, overlap={})",
                    len(chunks), file_path, self.chunk_size, self.chunk_overlap)
        return chunks
