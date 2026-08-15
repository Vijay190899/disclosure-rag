# ADR-0005: BM25 as the retrieval default, and no agent framework

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Two decisions about what the stack does *not* contain, both taken against the obvious choice.

## Retrieval: BM25, not hybrid

The intuition that hybrid retrieval beats either half is well founded in general and I expected it to
hold here: financial documents are full of exact figures and identifiers that embeddings
under-retrieve, so fusing lexical and dense results should win.

Measured on eight filings, retrieval scoped to the filing being asked about, with
`intfloat/multilingual-e5-large` and its required `query:` and `passage:` prefixes:

| Retriever | exact figure, n=320 | | | narrative, n=20 | | |
|---|---|---|---|---|---|---|
| | Recall@5 | MRR@10 | nDCG@10 | Recall@5 | MRR@10 | nDCG@10 |
| **BM25** | **0.478** | **0.352** | **0.401** | 0.200 | 0.080 | 0.143 |
| dense, multilingual-e5-large | 0.159 | 0.089 | 0.122 | 0.200 | 0.100 | 0.190 |
| hybrid, reciprocal rank fusion | 0.303 | 0.203 | 0.268 | 0.350 | 0.132 | 0.198 |

Paired bootstrap 95% intervals on the Recall@5 delta:

| Stratum | n | BM25 to dense | dense to hybrid |
|---|---|---|---|
| exact figure | 320 | **-0.319 [-0.378, -0.259]**, 124 disagreeing | +0.144 [+0.097, +0.191], 66 disagreeing |
| narrative | 20 | **+0.000 [-0.200, +0.200]**, 4 disagreeing | +0.150 [-0.100, +0.400], 7 disagreeing |

**Hybrid loses to plain BM25 on the exact-figure stratum, and not narrowly.** The mechanism is the
reason: a question there names the concept by the label the filer declared, and that label appears
verbatim in the row being looked for. There is no vocabulary gap for embeddings to bridge, so fusing
a weaker retriever in only costs ranking positions.

**On the narrative stratum the penalty disappears.** Those questions are phrased in the filing's own
management commentary and the answer is the statement row, so the words differ from the words that
find it. Dense goes from losing by 0.319 to losing by nothing, and hybrid has the best point estimate
on every metric. That is the mechanism above confirming itself from the other direction: BM25's
advantage was a property of the questions, not of retrieval.

**It does not overturn the decision, and saying so is the point of writing the threshold down
first.** Both narrative intervals span zero. On 20 questions a three-question difference cannot be
distinguished from noise, and no amount of favourable point estimates changes that. What can be said
is that the gap vanishes, not that it reverses.

**The dense path also imposes a cost on everything else.** e5-large reads 512 subword tokens, and at
a 600-token chunk budget 1618 of 1829 chunks exceed that and would be silently truncated. The whole
ladder therefore runs at 200 tokens, where every chunk fits. Smaller chunks cost recall: BM25 scores
Recall@5 of 0.553 at 600 tokens against 0.478 at 200. So adopting dense retrieval would mean giving
up recall across the system to accommodate the component that performs worst.

**Decision: BM25 is the default.** Dense and hybrid stay behind the `Retriever` protocol,
configurable, with no measured justification.

**What would change this** was pre-registered as a question set with genuine vocabulary mismatch,
where a reader phrases something differently from the document, rather than a larger model. That set
now exists, at n=20, and the result is above: it removes BM25's advantage without establishing a
replacement. The threshold for revisiting is therefore unchanged in kind and sharper in degree: a
narrative stratum large enough for the interval to exclude zero. On the observed effect size that is
roughly 150 to 200 confirmed pairs, against 20 today.

Getting there is a labelling problem rather than a modelling one, which is worth stating plainly:
the corpus yields about 28 reviewable candidates across eight filings, so the path runs through more
filings, not through a better extractor.

> An earlier version of this record reached the same conclusion from a weaker measurement: three
> filings, a 128-token model, and a chunk size chosen to fit it. The numbers above replace it.

## Orchestration: no agent framework, no MCP server

The answer loop is: classify the question, look up or retrieve, generate, check support. Four steps,
fixed order, no branching a model controls.

**That is a function, not an agent.** A framework earns its place when the number of tool calls is
unknown ahead of time and the model decides what to do next. Wrapping a fixed pipeline in one buys
nondeterminism, a worse latency tail, and a harder time answering "why did it do that".

The last point is decisive rather than incidental: this system's value is that its output can be
checked. Choosing the least predictable available orchestration to deliver verifiability would be
self-defeating.

**MCP** was in the original plan so the retrieval layer could be consumed as a standard tool. No
consumer exists other than this service, in the same process. It would put a process boundary, a
serialisation layer and a transport on the hot path in exchange for optionality nobody has asked for.
It is a couple of hours' work if a second consumer ever appears.

## What would bring them back

- **An agent framework** when the number of retrieval calls stops being predictable, for example
  multi-hop questions where a first retrieval determines the second query. That gets its own record.
- **MCP** when there is a consumer that is not this service.
- **Hybrid retrieval** when a longer-context embedder makes the dense side competitive on a properly
  sized question set.

## Also not built

AWS with ECS or EKS, for one stateless service and one in-memory index. A managed-model path, which is
unimplemented optionality. Ragas as a build gate, for the reason in ADR-0006.
