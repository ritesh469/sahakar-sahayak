"""Enterprise RAG app package.

Windows DLL load order (setup problem S9 in CLAUDE.md): if grpc (qdrant_client), psycopg2 and
torch are all loaded before pyarrow.dataset (pulled in lazily by sentence_transformers ->
datasets -> pandas), the process dies with an access violation. Loading pyarrow first, before
any of them, avoids it. Minimal repro:
    python -c "import grpc, psycopg2, torch, pyarrow.dataset"   # segfault on Windows
"""

import sys

if sys.platform == "win32":
    try:
        import pyarrow.dataset  # noqa: F401
    except ImportError:
        pass
