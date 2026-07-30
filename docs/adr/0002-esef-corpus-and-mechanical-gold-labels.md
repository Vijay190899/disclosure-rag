# ADR-0002: Real ESEF filings as the corpus, with gold labels generated from the tags

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

A citation benchmark needs to know the correct region on a page for each answer. Hand-labelling
bounding boxes is slow enough that a solo project produces a few dozen and stops, which is why
citation accuracy is rarely reported for document question answering.

Inline XBRL removes that cost. The tag is not a sidecar file, it wraps the number in the rendered
document:

```html
<ix:nonFraction name="ifrs-full:Revenue" contextRef="FY2024" unitRef="EUR"
                scale="6" decimals="-6">1,204</ix:nonFraction>
```

So the filer declares what the number means, and because the tag is an element in a rendered
document, its position can be recovered mechanically.

## Decision

**Corpus: real ESEF annual financial reports** from `filings.xbrl.org`, fetched by
`disclosure_rag.labels.fetch`.

**Gold labels: generated, not annotated.** Each tagged fact is wrapped in an anchor, the filing is
printed to PDF with headless Chromium, and the PDF link annotations are read back. An annotation
carries the page number and a rectangle in PDF coordinate space, produced by the same pagination pass
that produced the pages.

Result: **865 of 865 tagged facts located**, median IoU 0.947 against an independent text search for
the same figure. Two mechanisms that share no code agreeing is what makes the labels trustworthy.

**Country: Austria.** Germany is not available, because its officially appointed mechanism is the
Unternehmensregister and it does not publish into the open index. Austria is German-language, so the
multilingual and compound-noun properties of the corpus are preserved, and ESEF mechanics are
identical because they come from an EU regulation rather than a national one.

## Alternatives rejected

**Reading element geometry in the browser** with `getBoundingClientRect`. It located 0 of 600 facts.
Screen layout and print layout are different layouts: Chromium repaginates when printing, so an
element's scroll offset says nothing about which printed page it lands on. Link annotations come from
the pagination pass itself and cannot disagree with it.

**Mock or generated filings.** No external comparability, and self-authored questions grade
themselves.

**SEC EDGAR.** Free and unlimited, and rejected for two reasons: it is the most saturated corpus in
this problem space, and US filings do not carry the same convenient element-level geometry, which
would mean giving up the mechanical labels that make this benchmark possible.

**Bundesanzeiger and Unternehmensregister.** The richest German source, but bulk access is
commercially gated and the terms forbid scraping.

**Arelle for fact extraction.** Arelle resolves contexts, continuations and dimensions properly and
is the right tool at larger scale. An `lxml` reader over `ix:nonFraction` extracted 865 facts with
correct scale, sign, unit and period handling, so the heavier dependency is deferred until something
measurably needs it. Extraction sits behind a `FactSource` protocol, so it is a swap rather than a
rewrite.

## Trade-offs accepted

- **Tagging covers the primary statements.** Notes are block-tagged at best and narrative is untagged,
  so the free labels cover a specific slice.
- **`contextRef` must be handled correctly.** It resolves period and entity, and ignoring it would
  silently score prior-year comparatives as current-year figures. This is the highest-risk detail in
  the label plane and it has its own tests.
- **Displayed text is not the value.** `1,204` with `scale="6"` is 1204000000, and German filings use
  a decimal comma, so a naive reading is wrong by three orders of magnitude. Normalisation reads the
  `format` attribute, which declares the convention, and falls back to a digit-grouping heuristic.
- **Concept label coverage varies by filer.** Issuers must declare labels for their own extension
  concepts but may reference the official taxonomy for standard ones, so coverage ranged from 92 of 92
  concepts to 19 of 94 across three filings. Labels are pooled across the corpus to close the gap.
