"""Tests for reading concept labels out of a label linkbase."""

from pathlib import Path

from disclosure_rag.labels.taxonomy import concept_from_href, load_labels, parse_linkbase

LINKBASE = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:labelLink>
    <link:loc xlink:href="https://xbrl.ifrs.org/full_ifrs-cor.xsd#ifrs-full_Revenue"
              xlink:label="loc_rev"/>
    <link:label xlink:label="lab_rev" xml:lang="de"
                xlink:role="http://www.xbrl.org/2003/role/label">Umsatzerloese</link:label>
    <link:label xlink:label="lab_rev_total" xml:lang="de"
                xlink:role="http://www.xbrl.org/2003/role/totalLabel">Summe Umsatz</link:label>
    <link:label xlink:label="lab_rev_en" xml:lang="en"
                xlink:role="http://www.xbrl.org/2003/role/label">Revenue</link:label>
    <link:labelArc xlink:from="loc_rev" xlink:to="lab_rev"/>
    <link:labelArc xlink:from="loc_rev" xlink:to="lab_rev_total"/>
    <link:labelArc xlink:from="loc_rev" xlink:to="lab_rev_en"/>

    <link:loc xlink:href="issuer-2022.xsd#issuer_SonstigeErtraege" xlink:label="loc_own"/>
    <link:label xlink:label="lab_own" xml:lang="de"
                xlink:role="http://www.xbrl.org/2003/role/label">Sonstige Ertraege</link:label>
    <link:labelArc xlink:from="loc_own" xlink:to="lab_own"/>
  </link:labelLink>
</link:linkbase>
"""


def write(tmp_path: Path, name: str = "report_lab-de.xml") -> Path:
    path = tmp_path / name
    path.write_text(LINKBASE, encoding="utf-8")
    return path


def test_href_becomes_a_concept_name() -> None:
    assert concept_from_href("a.xsd#ifrs-full_Revenue") == "ifrs-full:Revenue"


def test_only_the_first_underscore_splits_prefix_from_local_name() -> None:
    """Local names contain underscores; prefixes do not."""
    assert concept_from_href("a.xsd#issuer_Sonstige_Ertraege") == "issuer:Sonstige_Ertraege"


def test_an_href_without_a_fragment_yields_nothing() -> None:
    assert concept_from_href("https://example.invalid/a.xsd") == ""


def test_standard_taxonomy_concepts_are_picked_up(tmp_path: Path) -> None:
    """Not only the issuer's own extensions, which is what makes this usable."""
    labels = parse_linkbase(write(tmp_path))
    assert labels["ifrs-full:Revenue"] == "Umsatzerloese"


def test_issuer_extension_concepts_are_picked_up(tmp_path: Path) -> None:
    labels = parse_linkbase(write(tmp_path))
    assert labels["issuer:SonstigeErtraege"] == "Sonstige Ertraege"


def test_the_plain_label_wins_over_presentation_variants(tmp_path: Path) -> None:
    """ "Summe Umsatz" is a total row heading, not the concept's name."""
    assert parse_linkbase(write(tmp_path))["ifrs-full:Revenue"] == "Umsatzerloese"


def test_the_requested_language_is_respected(tmp_path: Path) -> None:
    assert parse_linkbase(write(tmp_path), "en")["ifrs-full:Revenue"] == "Revenue"


def test_a_language_with_no_labels_yields_nothing(tmp_path: Path) -> None:
    assert parse_linkbase(write(tmp_path), "fr") == {}


def test_a_malformed_file_is_skipped_rather_than_raising(tmp_path: Path) -> None:
    """One bad linkbase in a corpus must not stop the whole build."""
    bad = tmp_path / "broken_lab.xml"
    bad.write_text("<not-xml", encoding="utf-8")
    assert parse_linkbase(bad) == {}


def test_a_missing_file_is_skipped(tmp_path: Path) -> None:
    assert parse_linkbase(tmp_path / "absent_lab.xml") == {}


def test_load_labels_finds_linkbases_by_name(tmp_path: Path) -> None:
    write(tmp_path)
    assert "ifrs-full:Revenue" in load_labels(tmp_path)


def test_load_labels_ignores_other_xml_in_the_package(tmp_path: Path) -> None:
    (tmp_path / "report_pre.xml").write_text(LINKBASE, encoding="utf-8")
    assert load_labels(tmp_path) == {}
