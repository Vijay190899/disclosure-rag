"""Group blocks into chunks without losing where they came from.

This module is the reason the project can cite a region at all, so it is worth
being explicit about what it refuses to do.

The obvious way to chunk is to join every block's text into one string and run a
splitter over it. That is how most pipelines do it, and it destroys provenance
the instant the join happens: offsets in the joined string no longer correspond
to any block, and the mapping back to a page region cannot be recovered
afterwards. Every citation then degrades to "somewhere in this passage", which
is the vague behaviour the README criticises.

So chunks are built by packing whole blocks in reading order, and each chunk
keeps the spans of the blocks that formed it. ADR-0004 has the full reasoning.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field

from disclosure_rag.ingest.blocks import Block
from disclosure_rag.provenance import Span

WORD = re.compile(r"\S+")

# Tokens are estimated rather than counted with a real tokenizer. The chunker
# only needs a consistent size budget, and pulling in a tokenizer to get from
# "about right" to "exact" would add a dependency for no measurable gain. The
# ratio is a rough average for mixed German and English financial text, where
# long compounds push it above the usual English figure.
TOKENS_PER_WORD = 1.6


def count_words(text: str) -> int:
    return len(WORD.findall(text))


def estimate_tokens(text: str) -> int:
    """Approximate token count. Consistent, not exact. See the note above."""
    return tokens_from_words(count_words(text))


def tokens_from_words(words: int) -> int:
    """The single conversion used everywhere, including the packing budget.

    Budgeting has to use this rather than summing per-block estimates. Each
    per-block ``int()`` discards up to a token, so a running sum over many small
    blocks underestimates the joined total and the chunk quietly overshoots. That
    is how one chunk reached 131 tokens against a 110 budget and tripped the
    embedding window guard.
    """
    return int(words * TOKENS_PER_WORD)


class Chunk(BaseModel):
    """A retrievable passage, and every region it occupies.

    ``spans`` is a list because a chunk assembled from several blocks occupies
    several regions, and a table continuing across a page break occupies regions
    on two pages. A single page and box cannot express that, which is the defect
    ADR-0004 exists to fix.
    """

    model_config = {"frozen": True}

    chunk_id: str
    document_id: str
    text: str
    spans: list[Span]
    order: int = Field(ge=0)
    token_count: int = 0

    @property
    def pages(self) -> list[int]:
        """Every page this chunk touches, in order."""
        return sorted({span.page for span in self.spans})


def _chunk_id(document_id: str, order: int, text: str) -> str:
    """Stable across runs, so re-ingesting the same document is idempotent (P7)."""
    digest = hashlib.sha256(f"{document_id}:{order}:{text}".encode()).hexdigest()[:12]
    return f"{document_id}:{order:05d}:{digest}"


def chunk_blocks(
    document_id: str,
    blocks: list[Block],
    target_tokens: int = 600,
    overlap_tokens: int = 80,
) -> list[Chunk]:
    """Pack blocks in reading order into chunks of roughly ``target_tokens``.

    Overlap is carried by repeating whole trailing blocks, not by copying a
    slice of text. A partial block would have no honest span, and inventing one
    is exactly the kind of quiet approximation that makes a citation metric
    meaningless.

    A block larger than the target on its own is split, and every piece keeps
    the **whole block's span**. That is the honest handling: the text genuinely
    does sit inside that region, so the citation is correct, merely wider than
    it needs to be. The cost lands on tightness rather than on truth, which is
    the right place for it. The alternative, emitting a single oversized chunk,
    looked tidier and turned out to break dense retrieval silently, because
    embedding models truncate without complaint.
    """
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be non-negative and below target_tokens")

    ordered = sorted(blocks, key=lambda block: block.order)
    # Budgets are held in words, because that is what the token estimate is
    # derived from. See tokens_from_words.
    word_budget = max(1, int(target_tokens / TOKENS_PER_WORD))
    overlap_budget = int(overlap_tokens / TOKENS_PER_WORD)

    chunks: list[Chunk] = []
    current: list[Block] = []
    current_words = 0

    def emit(group: list[Block]) -> None:
        text = "\n".join(block.text for block in group)
        order = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=_chunk_id(document_id, order, text),
                document_id=document_id,
                text=text,
                spans=[block.span for block in group],
                order=order,
                token_count=estimate_tokens(text),
            )
        )

    def carry_over(group: list[Block]) -> tuple[list[Block], int]:
        """Whole trailing blocks that fit inside the overlap budget."""
        carried: list[Block] = []
        carried_words = 0
        for block in reversed(group):
            words = count_words(block.text)
            if carried_words + words > overlap_budget:
                break
            carried.insert(0, block)
            carried_words += words
        return carried, carried_words

    def split_oversized(block: Block) -> list[Block]:
        """Break one long block into pieces, each keeping the full block span."""
        words = WORD.findall(block.text)
        return [
            Block(
                text=" ".join(words[start : start + word_budget]),
                span=block.span,
                order=block.order,
            )
            for start in range(0, len(words), word_budget)
        ]

    for block in ordered:
        pieces = split_oversized(block) if count_words(block.text) > word_budget else [block]
        for piece in pieces:
            piece_words = count_words(piece.text)
            if current and current_words + piece_words > word_budget:
                emit(current)
                current, current_words = carry_over(current)
                # The carry is a nicety; the budget is not. If overlap would push
                # the next chunk over, drop the overlap rather than the ceiling.
                if current_words + piece_words > word_budget:
                    current, current_words = [], 0
            current.append(piece)
            current_words += piece_words

    if current:
        emit(current)
    return chunks
