# ADR-0010: The ablation ladder, and the hybrid retrieval decision failing its first test

- **Status:** Accepted
- **Date:** 2026-07-29
- **Supersedes:** the hybrid retrieval row in [DECISIONS.md](../DECISIONS.md) dated 2026-07-07, as a
  default

## Context

DECISIONS.md has carried this since the first commit:

> Hybrid retrieval over dense-only. Financial docs are full of exact figures and codes that
> embeddings miss; BM25 + rerank covers the gap.

It has been labelled a hypothesis throughout, because there was nothing behind it. This is the run
that tests it.

Corpus: three Austrian ESEF filings. 120 questions in the exact-figure stratum, retrieval scoped to
the filing each question is about, gold spans covering every tagged occurrence of the figure.

## Four measurement bugs found first

Worth listing, because each one made a component look broken when the measurement was at fault, and
each now has a regression test.

1. **Embedding truncation.** Chunks averaged 576 tokens against the model's 128-token window, and
   fastembed truncates silently. Verified by embedding a 100-word text and the same text plus 400
   more words: cosine came back as exactly 1.0, so the extra words were never read. `DenseRetriever`
   now refuses to index chunks it cannot read in full, rather than scoring against a fraction of
   each one.
2. **The chunk budget did not hold.** Two separate leaks. A carried overlap plus a full-size piece
   could reach target plus overlap. And the packing loop summed per-block token estimates while the
   final count was computed on the joined text, so integer truncation per block let chunks overshoot.
   Budgets are now held in words, the unit the estimate derives from.
3. **Retrieval was not scoped to a document.** A question is about one filing, but the index held
   all three. These are Austrian bank annual reports with nearly identical wording, so unscoped
   dense retrieval returned only 4 of its top 10 from the document being asked about; the rest were
   the same income statement row in the wrong bank's report. Lexical retrieval degraded less,
   because exact figures differ between filings and gave it accidental document specificity.
4. **Gold recorded one location for figures reported in several.** Filings state a number in a
   highlights table and again in the full statement, tagging each occurrence separately. Keeping
   only the first made dense retrieval look broken while it was returning the consolidated statement
   on page 49 and being scored against page 25. All tagged occurrences of a concept and period are
   now gold, which is what `gold_spans` being a list was for.

## Result 1: chunk size, and a constraint I had not seen

Same questions, BM25 throughout, only the chunk budget changing.

| chunk tokens | chunks | recall@1 | recall@5 | recall@10 | coverage@1 | shown first when found |
|---|---|---|---|---|---|---|
| 110 | 5019 | 0.075 | 0.233 | 0.408 | 0.075 | 0.184 |
| 300 | 1706 | 0.108 | **0.408** | **0.533** | 0.108 | 0.203 |
| 600 | 799 | **0.208** | 0.375 | 0.508 | **0.208** | **0.410** |

**The important part is why 110 was ever tried.** It was not a hypothesis about retrieval. It was
the largest budget that fits the embedding model's 128-token window, chosen to satisfy the guard
from bug 1. Shrinking chunks to fit the model cost recall@1 nearly two thirds, from 0.208 to 0.075.

So the embedding model's context window is not a detail of the dense component. It propagates back
into chunking, and chunking is what lexical retrieval and citation tightness both depend on. A
128-token model does not merely retrieve less well, it forces a chunking regime that degrades
everything else.

**The conclusion is to fix the model, not the chunks.** A longer-context multilingual embedder,
`intfloat/multilingual-e5-large` at 512 tokens or bge-m3 at 8192, removes the constraint instead of
paying for it. That is the next rung rather than a settled decision, because it is untested here.

## Result 2: hybrid retrieval does not earn its place as a default

At 110 tokens, so every rung sees chunks the dense model can read in full:

| Retriever | recall@1 | recall@5 | recall@10 | coverage@1 | tightness |
|---|---|---|---|---|---|
| bm25 | 0.075 | **0.233** | **0.408** | 0.075 | 0.040 |
| dense (MiniLM multilingual) | 0.008 | 0.042 | 0.075 | 0.008 | 0.029 |
| hybrid (rrf) | 0.025 | 0.183 | 0.225 | 0.025 | 0.047 |

Paired bootstrap, 95%, recall@5:

- bm25 to dense: **-0.192 [-0.275, -0.117]**, 27 questions disagree
- dense to hybrid: **+0.142 [+0.075, +0.217]**, 21 questions disagree

**Hybrid loses to plain BM25**, 0.183 against 0.233. The decision from 2026-07-07 does not survive
its first measurement, and by the rule in ADR-0006 that a component which does not earn its row
comes out of the stack, hybrid is not justified as a default.

## Result 3: where it does earn its place

Splitting the same run by where the question's label came from. "Own" means the label the filing
itself declares, which appears verbatim in its text. "Pooled" means another issuer's label for the
same concept, so the query wording and the document wording genuinely differ.

| recall@5 | own label (n=86) | pooled label (n=34) |
|---|---|---|
| bm25 | **0.314** | 0.029 |
| dense | 0.035 | 0.059 |
| hybrid | 0.221 | **0.088** |

This is the honest version of the hybrid argument, and it is narrower than what DECISIONS.md
claimed. Where the query uses the document's own wording there is no vocabulary gap to bridge, and
lexical retrieval wins decisively; embeddings add nothing and dilute the ranking. Where the wording
differs, lexical collapses to 0.029 and hybrid triples it to 0.088.

So the original reasoning was right about the mechanism and wrong about the conclusion. Exact
figures and identifiers do favour lexical matching, which is exactly why hybrid is not a free
improvement: fusing a weaker retriever into a stronger one costs ranking positions.

**Decision: BM25 remains the default. Hybrid is retained as a configurable path, justified only for
queries whose wording is not the document's own.** Revisit when a longer-context embedder makes the
dense side competitive, which is a different experiment.

Caveat stated plainly: n=34 for the pooled group. The direction is consistent and the interval on
the pooled delta excludes zero, but this is one small group in one language on three filings, and it
should not be quoted as more than an indication.

## What these numbers are not

Absolute retrieval quality here is poor. The best configuration finds the answer in the top ten
about half the time and puts it first about a fifth. This is the easy control stratum, where the
question names a concept and a period and the answer sits in a table row, so the numbers should be
much better than they are.

Reported anyway, because a baseline is for beating and because the interesting figure is already
visible: at 600 tokens, when the answer is retrieved at all it is ranked first only 41% of the time.
The rest of the time the system has the right passage and would show a reader the wrong region. That
is the failure this project exists to expose, it is invisible to answer-level scoring, and it is
worse than I expected.

Likely causes of the low absolute numbers, in the order I would test them: table rows fragmenting
across chunks, the naive tokenizer against German compounds (risk R3, still open), and the absence
of any reranker. None of them are excuses, and all of them are rungs.
