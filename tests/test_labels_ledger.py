"""Tests for the ledger and the prose pairs drawn from it."""

from decimal import Decimal
from pathlib import Path

from disclosure_rag.labels.facts import Fact, LxmlFactSource
from disclosure_rag.labels.ledger import (
    FactLedger,
    build,
    extract_prose_pairs,
    is_prose,
    is_specific,
    resolve_to_fact,
    sentence_around,
)
from disclosure_rag.provenance import Span

FIXTURE = Path(__file__).parent / "fixtures" / "mini_filing.xhtml"


def fact(fact_id: str = "f000000", value: str = "1204000", concept: str = "x:Revenue") -> Fact:
    return Fact(fact_id=fact_id, concept=concept, displayed="1.204", value=Decimal(value))


def test_prose_is_told_apart_from_a_table_row() -> None:
    sentence = (
        "Die Gesamtaktiva der Gruppe beliefen sich zum Jahresende 2022 auf rund "
        "EUR 5.996,4 Mio und lagen damit deutlich ueber dem Vorjahr."
    )
    assert is_prose(sentence)


def test_a_table_row_is_not_prose() -> None:
    """Mostly digits and too few words, which is what a table row looks like."""
    assert not is_prose("Gesamt 197.315 737.935 4.230.415 5.287.706 10.453.371 1.234.567")


def test_a_short_line_is_not_prose() -> None:
    assert not is_prose("Umsatzerloese 1.204")


def test_a_heading_is_not_prose() -> None:
    assert not is_prose("KONZERNABSCHLUSS ZUM 31.12.2022 | 160")


def test_a_short_figure_is_not_specific_enough_to_match_on() -> None:
    """A bare three-digit number equals some fact in any large filing."""
    assert not is_specific("149")
    assert not is_specific("202")


def test_a_longer_figure_is_specific_enough() -> None:
    assert is_specific("1.057,1")
    assert is_specific("5.996,4")
    assert is_specific("737.935")


def test_a_page_header_block_does_not_yield_pairs() -> None:
    """Running headers repeat on every page and match things by accident.

    This is the case that made a first run report 638 pairs, most of them
    worthless, because whole-page text was being split into pseudo-sentences.
    """
    facts = LxmlFactSource().extract(FIXTURE)
    located = {item.fact_id: Span(page=0, x0=0.1, y0=0.1, x1=0.2, y1=0.2) for item in facts}
    header = [
        "ERLAEUTERUNGEN (NOTES) ZUM KONZERNABSCHLUSS | 4 FINANZINSTRUMENTE UND "
        "KREDITRISIKO JAHRESFINANZBERICHT ZUM 31.12.2022 | 101"
    ]
    assert extract_prose_pairs("doc", [header], facts, located) == []


def test_sentence_around_returns_the_containing_sentence() -> None:
    text = "Erster Satz hier. Zweiter Satz mit 1.204 darin. Dritter Satz."
    assert sentence_around(text, text.index("1.204")) == "Zweiter Satz mit 1.204 darin."


def test_resolution_matches_at_the_precision_the_prose_uses() -> None:
    """ "rund 1,2 Mrd" restates 1204000000, within the tolerance policy."""
    target = fact(value="1204000000")
    assert resolve_to_fact(Decimal("1.2"), [target]) is target


def test_resolution_rejects_a_figure_that_disagrees() -> None:
    assert resolve_to_fact(Decimal("1.3"), [fact(value="1204000000")]) is None


def test_resolution_ignores_zero_valued_facts() -> None:
    """Dividing by a zero fact would raise, and every figure would match it."""
    assert resolve_to_fact(Decimal("500"), [fact(value="0")]) is None


def test_prose_pairs_are_found_and_carry_the_gold_span() -> None:
    facts = LxmlFactSource().extract(FIXTURE)
    assets = next(item for item in facts if item.concept == "ifrs-full:Assets")
    gold = Span(page=4, x0=0.1, y0=0.2, x1=0.3, y1=0.25)

    page_blocks = [
        [
            "Die Gesamtaktiva der Gruppe beliefen sich zum Jahresende 2022 auf rund "
            "EUR 5.996,4 Mio und lagen damit deutlich ueber dem Niveau des Vorjahres."
        ]
    ]
    pairs = extract_prose_pairs("doc", page_blocks, facts, {assets.fact_id: gold})

    assert len(pairs) == 1
    assert pairs[0].concept == "ifrs-full:Assets"
    assert pairs[0].gold_span == gold
    assert pairs[0].page == 0


def test_prose_pairs_skip_facts_that_were_never_located() -> None:
    """A pair without a gold box is useless as a label, so it is not emitted."""
    facts = LxmlFactSource().extract(FIXTURE)
    page_blocks = [
        [
            "Die Gesamtaktiva der Gruppe beliefen sich zum Jahresende 2022 auf rund "
            "EUR 5.996,4 Mio und lagen damit deutlich ueber dem Niveau des Vorjahres."
        ]
    ]
    assert extract_prose_pairs("doc", page_blocks, facts, {}) == []


def test_table_rows_do_not_become_prose_pairs() -> None:
    facts = LxmlFactSource().extract(FIXTURE)
    located = {item.fact_id: Span(page=0, x0=0.1, y0=0.1, x1=0.2, y1=0.2) for item in facts}
    assert extract_prose_pairs("doc", [["Bilanzsumme 5.996,4 1.204 870"]], facts, located) == []


def test_build_reports_coverage_and_drops_unlocated_facts() -> None:
    facts = [fact("f000000"), fact("f000001", value="99000")]
    located = {"f000000": Span(page=0, x0=0.1, y0=0.1, x1=0.2, y1=0.2)}
    ledger = build("doc", facts, located)
    assert ledger.coverage == 0.5
    assert [row.fact.fact_id for row in ledger.facts] == ["f000000"]


def test_build_on_an_empty_document_does_not_divide_by_zero() -> None:
    assert build("doc", [], {}).coverage == 0.0


def test_ledger_round_trips_through_disk(tmp_path: Path) -> None:
    facts = [fact()]
    located = {"f000000": Span(page=7, x0=0.1, y0=0.1, x1=0.2, y1=0.2)}
    original = build("doc", facts, located)

    path = tmp_path / "ledger.json"
    original.write(path)
    restored = FactLedger.read(path)

    assert restored.document_id == "doc"
    assert restored.spans_for("f000000") == [Span(page=7, x0=0.1, y0=0.1, x1=0.2, y1=0.2)]
    assert restored.facts[0].fact.value == Decimal("1204000")
