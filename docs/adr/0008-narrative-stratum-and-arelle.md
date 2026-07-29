# ADR-0008: Keeping the benchmark honest after the reconciliation cut

- **Status:** Accepted
- **Date:** 2026-07-29
- **Follows:** [ADR-0007](0007-m0-probe-outcome.md)

## Context

[ADR-0007](0007-m0-probe-outcome.md) cut reconciliation because only 19 of 50 prose figures resolve
to a tagged fact. That was the right call for the feature. It also created a problem that the ADR
did not address, and which is more serious than the feature loss.

**The oracle construction was what kept the benchmark from being trivial.** [ADR-0003](0003-esef-corpus-and-labels.md)
identified the trap plainly: generating "what was revenue in 2022?" from a tagged fact asks the
system to find a number in a table that I already know is tagged and already know the location of.
It scores well and proves nothing. The stated defence was that the tagged statements act as an
oracle while the untagged narrative is the system under test.

With reconciliation gone, that defence is gone with it. If the evaluation set is built only from
tagged primary-statement facts, then citation IoU measures performance on the easiest possible
retrieval task and the headline number is not worth reporting.

This is the risk the project most needs to avoid, because the headline metric is the project.

## The observation that resolves it

The A1 measurement failed against its threshold but it did not return zero. The numbers underneath
it are more useful than the verdict:

| | Count |
|---|---|
| Untagged numeric mentions across 3 filings | 10738 |
| Of those, sitting in prose sentences | 1329 |
| Sampled for A1 | 50 |
| Resolving to a tagged fact | 19 (38%) |

Each such pair is a narrative sentence stating a figure, matched to a tagged fact that supplies the
value **and a gold bounding box**.

That is far too thin to build a reconciliation feature on, which is why ADR-0007 stands. It is
enough for an evaluation stratum. A question set of 30 narrative items needs 30 pairs.

### What the implementation actually yielded

Written after building the extractor against the same three filings, because the first number I
produced was wrong and the correction is the useful part.

| | Candidates |
|---|---|
| First run, sentences split from whole-page text | 638 |
| After reading layout blocks instead | 171 |
| Genuine on inspection of a sample | roughly half |

The first run was inflated by a mistake worth recording. I read page text with a plain
`get_text()`, which returns headers, tables and paragraphs concatenated into one string. Splitting
that into sentences produces blobs that pass a prose check while being nothing of the kind, so
running headers such as "JAHRESFINANZBERICHT ZUM 31.12.2022 | 101" became candidates. Reading
layout blocks keeps a paragraph a paragraph, and the count fell to 171.

A second filter came out of the same inspection: matching on value alone produces coincidences. In
a document holding hundreds of facts a bare "149" equals something almost always, so a figure now
needs at least four significant digits before a match counts.

Inspecting the survivors, roughly half are genuine. Real ones look like "Das Grundkapital der
Gesellschaft beträgt zum Stichtag EUR 195.000.000,00". The two failure modes that remain are table
rows whose layout block reads as prose, and value matches that are coincidence rather than
restatement, such as a headcount figure equalling a tagged equity value.

**So the output is a candidate pool, not a label set.** `ProsePair` carries a `confirmed` flag,
defaulting to false, and the build writes a review CSV. Only confirmed rows may be used as labels.
This is the same discipline the M0 probe applied to its own resolver, and it applies here for the
same reason: an automated pass narrows the field, and a person decides.

Roughly 85 genuine pairs from three filings still clears the 30 needed for the narrative stratum
with room to spare, and the corpus can widen to eight filings if it does not.

The distinction matters and is worth stating precisely: **a feature has to work on most inputs, an
evaluation set only has to be correct on the inputs it contains.** A 38% yield is a failure for the
first and an abundance for the second. I conflated the two when I designed M0, which is why one
threshold was carrying both questions.

## Decision

**1. The label plane persists resolved prose-to-fact pairs as a first-class output**, alongside the
fact ledger. Each pair records the sentence, the figure as written, the resolved fact, and the
fact's gold span.

**2. The evaluation set draws its narrative stratum from those pairs.** A narrative question asks
about a figure where it appears in prose, and the gold location is the tagged fact's box. The
system under test still only ever sees the rendered PDF, so it has to find the number by retrieval.
Nothing about the tag is available to it.

**3. Citation IoU is reported per stratum, never pooled.** Pooling would let the easy
primary-statement stratum mask performance on the narrative one, which is the failure this ADR
exists to prevent. The exact-figure stratum stays in the set as the easy control, and it is labelled
as such.

## Consequences

- The headline metric keeps a hard stratum, so the number means something.
- The 30-item narrative stratum in the evaluation design stops needing hand annotation for its gold
  boxes, which was the largest remaining manual cost in M2.
- The unanswerable stratum still needs hand construction. That is unchanged and correct: absence
  cannot be labelled mechanically.
- M1 grows a second output. Small, and it is the same join the probe already performs.

## A second decision, recorded here because it is adjacent

**Arelle is deferred. The label plane starts with the lxml reader proven in M0.**

The roadmap said M1 would replace the probe's lxml extraction with Arelle so that contexts,
continuations and dimensions resolve properly. Having run the probe, I am not doing that yet.

The lxml path extracted 865 facts across three filings with correct scale, sign and period handling,
verified against both the Austrian thousands convention and the German decimal comma. It works.
Arelle would add a large dependency and a slower run to solve problems I have not yet measured
having: `ix:continuation` for facts split across elements, dimensional qualification, and unit
resolution beyond the raw `unitRef`.

This is the same reasoning [ADR-0006](0006-deterministic-evaluation-gate.md) applied to Cohere, and
the same reasoning [ADR-0002](0002-pymupdf-for-parsing.md) applied to Docling: do not add the
heavier tool before establishing that the lighter one falls short. Consistency here matters, because
the alternative is a project where the rule applies to vendors I was not excited about and not to
the ones I was.

Extraction sits behind a `FactSource` protocol, so this is a swap rather than a rewrite.

**Revisit if:** continuation-split facts appear in the corpus at a rate that shows up in the M2
failure taxonomy, dimensional qualification turns out to be needed to disambiguate two facts of the
same concept and period, or the ledger disagrees with a filer's own viewer on a value.
