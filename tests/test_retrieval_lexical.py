"""Tests for the BM25 baseline."""

from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.provenance import Span
from disclosure_rag.retrieval.lexical import BM25Retriever, tokenize


def chunk(chunk_id: str, text: str, page: int = 0) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc",
        text=text,
        spans=[Span(page=page, x0=0.1, y0=0.1, x1=0.9, y1=0.2)],
        order=int(chunk_id[-1]),
    )


def test_a_figure_keeps_its_separators_as_one_token() -> None:
    """Exact figures are the reason lexical retrieval is expected to help."""
    assert "5.996,4" in tokenize("Bilanzsumme 5.996,4 Mio")


def test_tokens_are_lowercased() -> None:
    assert tokenize("Bilanzsumme EUR") == ["bilanzsumme", "eur"]


def test_umlauts_survive_tokenisation() -> None:
    assert "umsatzerlöse" in tokenize("Umsatzerlöse gestiegen")


def test_an_empty_index_returns_nothing() -> None:
    assert BM25Retriever().search("anything") == []


def test_the_matching_chunk_ranks_first() -> None:
    retriever = BM25Retriever()
    retriever.index(
        [
            chunk("c0", "Umsatzerlöse des Konzerns im Geschäftsjahr"),
            chunk("c1", "Bilanzsumme und Eigenkapital der Gruppe"),
            chunk("c2", "Anzahl der Mitarbeiter zum Jahresende"),
        ]
    )
    assert retriever.search("Bilanzsumme Eigenkapital")[0].chunk.chunk_id == "c1"


def test_results_come_back_ranked() -> None:
    retriever = BM25Retriever()
    retriever.index([chunk(f"c{i}", f"eigenkapital {'füller ' * i}") for i in range(4)])
    scores = [hit.score for hit in retriever.search("eigenkapital")]
    assert scores == sorted(scores, reverse=True)


def test_top_k_is_respected() -> None:
    retriever = BM25Retriever()
    retriever.index([chunk(f"c{i}", "eigenkapital gruppe") for i in range(6)])
    assert len(retriever.search("eigenkapital", top_k=3)) == 3


def test_a_query_matching_nothing_returns_nothing() -> None:
    retriever = BM25Retriever()
    retriever.index([chunk("c0", "eigenkapital")])
    assert retriever.search("völlig unbezogener begriff") == []


def test_ranking_is_reproducible_when_scores_tie() -> None:
    """A benchmark whose ordering wobbles between runs is not a benchmark."""
    retriever = BM25Retriever()
    retriever.index([chunk(f"c{i}", "identischer text hier") for i in range(5)])
    first = [hit.chunk.chunk_id for hit in retriever.search("identischer text")]
    second = [hit.chunk.chunk_id for hit in retriever.search("identischer text")]
    assert first == second


def test_reindexing_replaces_rather_than_appends() -> None:
    retriever = BM25Retriever()
    retriever.index([chunk("c0", "eigenkapital")])
    retriever.index([chunk("c1", "eigenkapital")])
    hits = retriever.search("eigenkapital")
    assert [hit.chunk.chunk_id for hit in hits] == ["c1"]


def test_a_result_exposes_the_spans_it_would_cite() -> None:
    retriever = BM25Retriever()
    retriever.index([chunk("c0", "eigenkapital", page=7)])
    assert retriever.search("eigenkapital")[0].spans[0].page == 7


def test_search_can_be_scoped_to_one_document() -> None:
    """A passage from another filing is wrong however well it matches."""
    retriever = BM25Retriever()
    a = Chunk(
        chunk_id="a0",
        document_id="doc-a",
        text="eigenkapital der gruppe",
        spans=[Span(page=0, x0=0.1, y0=0.1, x1=0.9, y1=0.2)],
        order=0,
    )
    b = Chunk(
        chunk_id="b0",
        document_id="doc-b",
        text="eigenkapital der gruppe",
        spans=[Span(page=0, x0=0.1, y0=0.1, x1=0.9, y1=0.2)],
        order=0,
    )
    retriever.index([a, b])
    hits = retriever.search("eigenkapital", document_id="doc-b")
    assert [hit.chunk.chunk_id for hit in hits] == ["b0"]


def test_an_unknown_document_scope_returns_nothing() -> None:
    retriever = BM25Retriever()
    retriever.index([chunk("c0", "eigenkapital")])
    assert retriever.search("eigenkapital", document_id="absent") == []
