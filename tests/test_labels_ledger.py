"""Tests for the ledger and the prose pairs drawn from it."""

from decimal import Decimal
from pathlib import Path

from disclosure_rag.labels.facts import Fact, LxmlFactSource
from disclosure_rag.labels.ledger import (
    FactLedger,
    ProsePair,
    build,
    extract_prose_pairs,
    is_prose,
    is_specific,
    names_concept,
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


def test_a_sentence_naming_the_concept_passes_the_precision_gate() -> None:
    """Value agreement alone is coincidence-prone; naming the concept is evidence."""
    assert names_concept(
        "Die Bilanzsumme des Konzerns belief sich zum Jahresende auf EUR 5.996,4 Mio.",
        "Bilanzsumme",
    )


def test_a_multi_word_label_needs_most_of_its_words() -> None:
    label = "Zinserträge unter Anwendung der Effektivzinsmethode"
    assert names_concept(f"Die {label} betrugen 192,9 Mio EUR im Berichtsjahr.", label)
    assert not names_concept("Die Zinserträge betrugen 192,9 Mio EUR im Berichtsjahr.", label)


def test_an_unrelated_sentence_fails_the_gate() -> None:
    assert not names_concept(
        "Die Anzahl der Mitarbeiter stieg im Berichtsjahr auf 1.204 Personen.", "Bilanzsumme"
    )


def test_a_concept_with_no_label_fails_the_gate() -> None:
    assert not names_concept("Ein beliebiger Satz mit einer Zahl 1.204 darin.", "")


def test_prose_pairs_record_whether_they_named_the_concept() -> None:
    facts = LxmlFactSource().extract(FIXTURE)
    assets = next(item for item in facts if item.concept == "ifrs-full:Assets")
    gold = Span(page=4, x0=0.1, y0=0.2, x1=0.3, y1=0.25)
    blocks = [
        [
            "Die Gesamtaktiva der Gruppe beliefen sich zum Jahresende 2022 auf rund "
            "EUR 5.996,4 Mio und lagen damit deutlich ueber dem Niveau des Vorjahres."
        ]
    ]
    pairs = extract_prose_pairs(
        "doc",
        blocks,
        facts,
        {assets.fact_id: gold},
        None,
        {"ifrs-full:Assets": "Gesamtaktiva"},
    )
    assert pairs and pairs[0].names_concept is True


def test_a_concept_with_no_declared_label_shows_a_borrowed_wording() -> None:
    """Asking a reviewer whether a German sentence is about
    "ifrs-full:CurrentAssets" adds a translation task to the judgement."""
    from disclosure_rag.labels.review import wording

    pair = ProsePair(
        document_id="doc",
        sentence="Bei den kurzfristigen Vermoegenswerten zeigte sich eine Erhoehung.",
        mention="797,4",
        page=91,
        fact_id="f1",
        concept="ifrs-full:CurrentAssets",
        value=Decimal("797432000"),
        gold_span=Span(page=91, x0=0.1, y0=0.1, x1=0.2, y1=0.2),
    )
    ledger = FactLedger(document_id="doc", concept_labels={})
    shown = wording(pair, ledger, {"ifrs-full:CurrentAssets": {"Kurzfristige Vermoegenswerte"}})
    assert shown.startswith("Kurzfristige Vermoegenswerte")
    assert "ifrs-full:CurrentAssets" in shown


def test_the_filings_own_label_wins_over_a_borrowed_one() -> None:
    from disclosure_rag.labels.review import wording

    pair = ProsePair(
        document_id="doc",
        sentence="Die Bilanzsumme stieg.",
        mention="162,8",
        page=1,
        fact_id="f1",
        concept="ifrs-full:Assets",
        value=Decimal("162788000"),
        gold_span=Span(page=1, x0=0.1, y0=0.1, x1=0.2, y1=0.2),
    )
    ledger = FactLedger(document_id="doc", concept_labels={"ifrs-full:Assets": "Bilanzsumme"})
    assert wording(pair, ledger, {"ifrs-full:Assets": {"Summe Aktiva"}}) == "Bilanzsumme"


def test_confirming_one_sentence_does_not_confirm_another(tmp_path: Path) -> None:
    """One tagged fact can be restated in several places.

    Keyed on fact id and the figure as written, confirming the sentence on one
    page silently confirmed a different sentence on another that quoted the same
    number. A reviewer cannot see that happen, so the key has to be wide enough
    that they never have to.
    """
    from disclosure_rag.labels.review import identity

    span = Span(page=1, x0=0.1, y0=0.1, x1=0.2, y1=0.2)

    def pair(sentence: str, page: int) -> ProsePair:
        return ProsePair(
            document_id="doc",
            sentence=sentence,
            mention="-1.275",
            page=page,
            fact_id="f1",
            concept="ifrs-full:CashFlows",
            value=Decimal("-1275000"),
            gold_span=span,
        )

    reviewed = pair("Aus der Geldflussrechnung resultiert ...", 25)
    elsewhere = pair("TEUR 1.863 wirkten ebenfalls auf ...", 103)
    assert identity(reviewed) != identity(elsewhere)

    decisions = {identity(reviewed): True}
    updated = [
        item.model_copy(update={"confirmed": True}) if decisions.get(identity(item)) else item
        for item in (reviewed, elsewhere)
    ]
    assert [item.confirmed for item in updated] == [True, False]
