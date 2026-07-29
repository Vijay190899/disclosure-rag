# Stack

What this project uses, why, and what I deliberately took out. Anything listed here that is not yet
installed is marked as planned, so this file can be checked against `pyproject.toml` without
finding a gap.

## Language and runtime

- **Python 3.12.** Default for anything model-adjacent.
- **uv** for packaging and virtualenvs. Fast, and the lockfile is what makes the container image
  and CI run the same dependency set.

## Serving

- **FastAPI**, async. Ingestion and retrieval are I/O bound, so async earns its keep.
- **Uvicorn** as the ASGI server.
- **Pydantic** and **pydantic-settings** for request models and configuration. Settings are grouped
  per pipeline stage rather than kept flat, because a five-stage pipeline produces a lot of knobs.

## Label plane (planned, M1)

This is the part of the stack that does not appear in other RAG projects, and it is built first.

- **Arelle** to extract Inline XBRL facts: concept, value, unit, `scale`, `sign` and `contextRef`.
  `contextRef` is what distinguishes the current year from the prior-year comparative, and ignoring
  it would silently corrupt every label.
- **Playwright** driving headless Chromium to print the filing to PDF, with each tagged fact wrapped
  in an anchor beforehand. Chromium preserves anchors as PDF link annotations carrying a page number
  and a rectangle, and **PyMuPDF** reads them back.

  The obvious approach, reading `getBoundingClientRect()` in the browser, does not work: it located
  0 of 600 facts, because screen layout and print layout are different layouts and Chromium
  repaginates when printing. Link annotations come from the pagination pass itself. Measured at
  865 of 865 facts located, median IoU 0.947. See [ADR-0007](adr/0007-m0-probe-outcome.md).
- **Corpus: Austrian ESEF filings.** German-language, so the compound-noun argument holds, and the
  ESEF mechanics are identical because they come from an EU regulation. Germany itself is not
  available: its officially appointed mechanism is the Unternehmensregister, which does not publish
  into the open index.

## Serving plane (planned, M2 to M4)

- **PyMuPDF** for parsing. Block-level bounding boxes natively, offline, no per-page cost, and it
  renders pages with regions drawn on them, which is the same code path the citation viewer needs.
  Rejected: LlamaParse (per-page cost, and geometry does not survive the markdown output) and
  ColPali (a visual retrieval model, not a parser: it would remove the chunker and make lexical
  retrieval and text reranking impossible). Full reasoning in
  [ADR-0002](adr/0002-pymupdf-for-parsing.md). **Docling** is the named upgrade path if table
  structure turns out to be the binding constraint.
- **Span-preserving chunking.** Contiguous blocks in reading order, packed to a token budget, each
  chunk carrying the list of page regions it covers. Chunking over the block list rather than over
  a concatenated string is the whole reason citations can resolve to a region at all.
- **bge-m3** for embeddings. Multilingual, which matters because these are German filings, and it
  produces dense and learned-sparse representations from one model.
- **Qdrant** for storage, with named vectors for the dense and sparse sides. Hybrid support is
  native and it runs as a local container in development.
- **BM25** as the lexical side, fused with dense results using reciprocal rank fusion. Financial
  documents are full of exact figures and identifiers that embeddings under-retrieve. This is a
  hypothesis until the delta row in the results table exists.
- **bge-reranker-v2-m3** as the cross-encoder. Open, multilingual and self-hosted. I would rather
  publish the improvement a reranker buys than add a paid vendor before establishing that one is
  needed.

## Evaluation (planned, M2 onward)

- **Deterministic retrieval and citation metrics** against fixed relevance judgements: recall@k,
  nDCG@10, and citation IoU@0.5 against the ledger's bounding boxes. These gate CI, because they
  are reproducible and free.
- **Model-judged metrics** for answer faithfulness run nightly and off the critical path. A build
  that turns red because a judge model felt different today is a build I would learn to ignore.
  Reasoning in [ADR-0006](adr/0006-deterministic-evaluation-gate.md).

## Ops

- **Docker** for local parity. Non-root user, pinned base tooling, healthcheck.
- **GitHub Actions** for lint, typecheck, hooks and tests. The evaluation gate joins once there is
  an evaluation harness to gate on, and not before.
- **mypy** in strict mode. Ten minutes to add now, days to retrofit later.

## Frontend (planned, M6)

A thin citation viewer: answer on one side, the rendered page with the cited region outlined on the
other. Streamlit, because the interesting part is the highlight endpoint and not the framework.

## Taken out, and staying out

Recording these because a stack is defined as much by what it refuses as by what it includes. Each
was in the original plan.

| Removed | Why |
|---|---|
| OpenAI Agents SDK | The answer loop is a fixed pipeline with no dynamic control flow. A framework would add nondeterminism and make "why did it do that" harder, on a project whose entire thesis is verifiability. |
| MCP retrieval server | No consumer exists. It puts a process boundary and a serialisation layer on the hot path in exchange for optionality nobody has asked for. It is a couple of hours' work later if a reason appears. |
| Cohere Rerank | A paid vendor added before establishing that reranking helps. An open cross-encoder gives the same measurement without the dependency. |
| LlamaParse | Per-page cost on 400-page documents, and the bounding boxes do not survive to the markdown output that the rest of the pipeline would consume. |
| ColPali | Not an alternative parser. It replaces the retrieval architecture, removes the chunker, and cannot be fused with BM25. Reasonable experiment later, not a v1 fork. |
| AWS, ECS and EKS | One stateless service and one database. Kubernetes is the wrong size and "ECS/EKS" was two options presented as a decision. |
| Bedrock | Unimplemented optionality is noise. |
| Next.js | Scope that does not exist yet. |
| Ragas as a CI gate | Kept as a nightly metric. It is model-judged, so gating a build on it makes the build nondeterministic and costly. |

## Deliberately out of scope

- Fine-tuning. A separate project covers it, and here the grounding and the measurement are the
  interesting part.
- General chat unrelated to the ingested corpus.
- Automated regulatory decisions. This assists a human reviewer and does not replace one.
