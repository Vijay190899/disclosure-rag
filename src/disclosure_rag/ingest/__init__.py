"""The ingest stage of the serving plane.

Turns a rendered PDF into chunks that still know where they came from. This is
the half of the system under test: it reads only the printed document, never the
Inline XBRL, so nothing here may import from ``disclosure_rag.labels``.
"""

from disclosure_rag.ingest.blocks import Block, extract_blocks
from disclosure_rag.ingest.chunker import Chunk, chunk_blocks, estimate_tokens

__all__ = ["Block", "Chunk", "chunk_blocks", "estimate_tokens", "extract_blocks"]
