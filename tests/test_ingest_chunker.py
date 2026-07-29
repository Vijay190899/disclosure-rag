"""Tests for span-preserving chunking.

The property under test throughout: a chunk's spans must account for every block
that went into it. If that ever stops holding, citations silently start pointing
at regions the text did not come from, and no other test in the suite would
notice.
"""

import pytest

from disclosure_rag.ingest.blocks import Block
from disclosure_rag.ingest.chunker import chunk_blocks, estimate_tokens
from disclosure_rag.provenance import Span


def block(order: int, text: str = "wort " * 50, page: int = 0) -> Block:
    height = 0.02
    top = min(0.9, order * height)
    return Block(
        text=text.strip(),
        span=Span(page=page, x0=0.1, y0=top, x1=0.9, y1=top + 0.01),
        order=order,
    )


def test_a_chunk_carries_one_span_per_source_block() -> None:
    blocks = [block(i) for i in range(3)]
    chunks = chunk_blocks("doc", blocks, target_tokens=10_000, overlap_tokens=0)
    assert len(chunks) == 1
    assert chunks[0].spans == [b.span for b in blocks]


def test_every_block_appears_in_some_chunk() -> None:
    blocks = [block(i) for i in range(25)]
    chunks = chunk_blocks("doc", blocks, target_tokens=200, overlap_tokens=0)
    covered = {span for chunk in chunks for span in chunk.spans}
    assert covered == {b.span for b in blocks}


def test_text_and_spans_stay_in_step() -> None:
    """The invariant that makes citation scoring meaningful."""
    blocks = [block(i, text=f"block{i} " * 40) for i in range(12)]
    for chunk in chunk_blocks("doc", blocks, target_tokens=150, overlap_tokens=0):
        assert len(chunk.text.split("\n")) == len(chunk.spans)


def test_chunks_respect_the_token_budget() -> None:
    blocks = [block(i, text="wort " * 30) for i in range(20)]
    chunks = chunk_blocks("doc", blocks, target_tokens=120, overlap_tokens=0)
    assert all(chunk.token_count <= 120 for chunk in chunks)


def test_an_oversized_block_is_split_but_every_piece_keeps_the_whole_span() -> None:
    """The citation stays truthful; only its tightness suffers.

    Emitting one oversized chunk instead looked tidier and silently broke dense
    retrieval, because embedding models truncate without complaint.
    """
    blocks = [block(0, text="wort " * 500)]
    chunks = chunk_blocks("doc", blocks, target_tokens=100, overlap_tokens=0)
    assert len(chunks) > 1
    assert all(chunk.spans == [blocks[0].span] for chunk in chunks)


def test_no_chunk_exceeds_the_budget_even_from_one_huge_block() -> None:
    """The property the dense retriever's window guard depends on."""
    blocks = [block(0, text="wort " * 2000), block(1, text="wort " * 30)]
    chunks = chunk_blocks("doc", blocks, target_tokens=100, overlap_tokens=0)
    assert all(chunk.token_count <= 100 for chunk in chunks)


def test_splitting_preserves_all_the_words() -> None:
    blocks = [block(0, text=" ".join(f"w{i}" for i in range(300)))]
    chunks = chunk_blocks("doc", blocks, target_tokens=100, overlap_tokens=0)
    recovered = " ".join(chunk.text for chunk in chunks).split()
    assert recovered == [f"w{i}" for i in range(300)]


def test_overlap_repeats_whole_blocks() -> None:
    blocks = [block(i, text=f"b{i} " * 40) for i in range(10)]
    chunks = chunk_blocks("doc", blocks, target_tokens=150, overlap_tokens=70)
    assert len(chunks) > 1
    # The overlap must be a block that genuinely appears in the previous chunk,
    # never a slice of one, because a slice would have no span of its own.
    shared = set(chunks[0].spans) & set(chunks[1].spans)
    assert shared


def test_a_chunk_spanning_a_page_break_keeps_both_pages() -> None:
    """The motivating example from the README, asserted directly."""
    blocks = [block(0, page=3), block(1, page=4)]
    chunks = chunk_blocks("doc", blocks, target_tokens=10_000, overlap_tokens=0)
    assert chunks[0].pages == [3, 4]


def test_chunk_ids_are_stable_across_runs() -> None:
    """Re-ingesting the same document must replace chunks, not duplicate them."""
    blocks = [block(i) for i in range(6)]
    first = chunk_blocks("doc", blocks, target_tokens=200, overlap_tokens=0)
    second = chunk_blocks("doc", blocks, target_tokens=200, overlap_tokens=0)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_different_documents_get_different_chunk_ids() -> None:
    blocks = [block(0)]
    a = chunk_blocks("doc-a", blocks)[0]
    b = chunk_blocks("doc-b", blocks)[0]
    assert a.chunk_id != b.chunk_id


def test_blocks_are_read_in_order_even_if_supplied_shuffled() -> None:
    blocks = [block(2), block(0), block(1)]
    chunk = chunk_blocks("doc", blocks, target_tokens=10_000, overlap_tokens=0)[0]
    assert chunk.text.split("\n")[0].startswith("wort")
    assert [span.y0 for span in chunk.spans] == sorted(span.y0 for span in chunk.spans)


def test_no_blocks_produces_no_chunks() -> None:
    assert chunk_blocks("doc", []) == []


@pytest.mark.parametrize(("target", "overlap"), [(0, 0), (-1, 0), (100, 100), (100, -1)])
def test_invalid_budgets_are_rejected(target: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_blocks("doc", [block(0)], target_tokens=target, overlap_tokens=overlap)


def test_token_estimate_grows_with_length() -> None:
    assert estimate_tokens("ein zwei drei") > estimate_tokens("ein")
    assert estimate_tokens("") == 0


def test_overlap_never_pushes_a_chunk_over_the_budget() -> None:
    """The carry is a nicety; the budget is not.

    Without this, a carried overlap plus a full-size piece reached target plus
    overlap, and 30 chunks slipped past a 110-token budget at 131 tokens.
    """
    blocks = [block(i, text="wort " * 68) for i in range(12)]
    chunks = chunk_blocks("doc", blocks, target_tokens=110, overlap_tokens=20)
    assert chunks
    assert all(chunk.token_count <= 110 for chunk in chunks)
