# ADR-0005: BM25 as the retrieval default, and no agent framework

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Two decisions about what the stack does *not* contain, both taken against the obvious choice.

## Retrieval: BM25, not hybrid

The intuition that hybrid retrieval beats either half is well founded in general and I expected it to
hold here: financial documents are full of exact figures and identifiers that embeddings
under-retrieve, so fusing lexical and dense results should win.

Measured on 120 questions, retrieval scoped to the filing being asked about:

| Retriever | Recall@5 |
|---|---|
| BM25 | **0.233** |
| Dense, multilingual MiniLM | 0.042 |
| Hybrid, reciprocal rank fusion | 0.183 |

Paired bootstrap 95% interval on the delta: BM25 to dense **-0.192 [-0.275, -0.117]**.

**Hybrid loses to plain BM25.** The reason is the mechanism working against the conclusion. Where a
question uses the document's own wording there is no vocabulary gap for embeddings to bridge, lexical
matching wins outright, and fusing a weaker retriever in costs ranking positions rather than adding
recall.

**Decision: BM25 is the default.** Dense and hybrid retrieval stay in the codebase behind the
`Retriever` protocol, configurable and currently without a measured justification, which is a weaker
claim than the one I started with.

**Revisit** with a longer-context multilingual embedder. The dense row above was measured with a
128-token window against chunks that had to be shrunk to fit it, and shrinking chunks to satisfy the
embedder cost Recall@1 nearly two thirds. A 512-token or larger model removes that constraint rather
than paying for it, and it is a different experiment from this one.

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
