# Stack

What is in the system, and what was deliberately kept out. Checkable against `pyproject.toml`.

## Runtime

- **Python 3.12**, packaged with **uv**. The committed lockfile is what makes CI and the container
  image install the same dependency set.

## Serving

- **FastAPI** and **Uvicorn**, with **Pydantic** for request and response contracts and
  **pydantic-settings** for configuration grouped per pipeline stage.
- No external model calls in the default configuration. The extractive generator runs locally, so the
  service and the whole benchmark run with no credentials and no network.

## Ingestion and citation

- **PyMuPDF** for block parsing, page rendering and region outlining. Geometry comes out of the parser
  natively, and the renderer is the same library, so the outline lands where the parser said the text
  was. [ADR-0004](adr/0004-pymupdf-for-parsing-and-rendering.md).
- **Span-preserving chunking**, built in-repo. Blocks are packed in reading order and each chunk keeps
  the list of page regions it covers, which is what makes a citation resolvable to a region rather than
  a passage. [ADR-0003](adr/0003-provenance-is-a-list-of-spans.md).

## Structured layer

- **lxml** reads `ix:nonFraction` elements out of the Inline XBRL: concept, value, `scale`, `sign`,
  `unitRef` and `contextRef`. `contextRef` distinguishes the current year from the prior-year
  comparative, and `unitRef` resolves through the unit declaration so a fact reports `EUR` rather than
  a document-local id.
- **Playwright** driving headless Chromium prints the filing to PDF with each tagged fact wrapped in an
  anchor. Chromium preserves anchors as PDF link annotations carrying a page and a rectangle, and
  PyMuPDF reads them back. That is how gold citation boxes are produced without hand annotation.
  [ADR-0002](adr/0002-esef-corpus-and-mechanical-gold-labels.md).
- **httpx** fetches report packages from `filings.xbrl.org`.

Extraction sits behind a `FactSource` protocol. **Arelle** is the upgrade path when contexts,
continuations or dimensions need fuller resolution than an attribute reader gives.

## Retrieval

- **BM25**, implemented in-repo. No model download, no server, so a full evaluation run takes seconds
  and anyone can reproduce it. This is the default, and the measurement behind that choice is in
  [ADR-0005](adr/0005-bm25-default-no-agent-framework.md).
- **fastembed** provides optional dense retrieval, ONNX rather than torch to keep the install small,
  with reciprocal rank fusion for a hybrid path. Both are configurable and currently carry no measured
  justification over BM25 alone.
- **qdrant-client** is present for corpora that outgrow one machine. At a few thousand chunks an
  in-memory index beats a network round trip, so it is not used by default.

## Evaluation

Deterministic and seeded. Retrieval reports Recall@k, MRR@10, nDCG@10 and citation IoU against boxes
taken from the filings' own tags. End to end reports routing accuracy, answer exact match, abstention
precision and recall, false answer rate, wrong-period trap survival and latency percentiles. Deltas
between configurations come with paired bootstrap intervals.
[ADR-0006](adr/0006-deterministic-evaluation.md).

## Quality and operations

- **mypy** in strict mode over `src` and `tests`, **ruff** for lint and format, **pre-commit** running
  the project's own ruff so the hooks and CI cannot disagree.
- **pytest**, 159 tests, including a guard that `ingest`, `retrieval` and `citation` cannot import the
  label plane.
- **Docker**: non-root user, pinned base tooling, healthcheck, no corpus baked into the image.
- **GitHub Actions** runs lint, typecheck, hooks and tests with least-privilege permissions and a
  concurrency group.

## Kept out

A stack is defined as much by what it refuses.

| Not used | Why |
|---|---|
| Agent framework | The answer loop is four fixed steps with no model-controlled branching. A framework buys nondeterminism on a system whose value is verifiability. |
| MCP server | No consumer other than this service, in the same process. It would put a transport on the hot path for optionality nobody asked for. |
| Hybrid retrieval as the default | Measured: it loses to plain BM25 on this corpus. Kept configurable, with no measured justification. |
| Cross-encoder reranker | It reads the same passage text that lacks the information distinguishing one period's figure from another's, so it cannot fix the failure that matters here. |
| LlamaParse | Per-page cost on 400-page filings, and bounding boxes do not survive to the markdown the pipeline would consume. |
| ColPali | A visual retrieval model rather than a parser. It removes the chunker and cannot be fused with lexical retrieval. |
| Managed cloud orchestration | One stateless service and one in-memory index. |
| Model-judged metrics as a build gate | Nondeterministic, paid per run, and at this sample size their variance is comparable to the regression they would catch. |

## Out of scope

Fine-tuning. General chat unrelated to the corpus. Automated regulatory decisions: this assists a
human reviewer.
