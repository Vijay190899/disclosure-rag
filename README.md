# disclosure-rag

**Question answering over EU annual financial reports, where every answer points at the exact figure
it came from.** A router sends questions about tagged figures to a structured lookup and everything
else to retrieval, so numbers are exact rather than approximated, and unsupported questions are
declined rather than guessed at.

![A cited figure outlined on the source page](docs/images/citation.png)

*"Wie hoch war Zinserträge unter Anwendung der Effektivzinsmethode im Geschäftsjahr 2022?"*
→ `192.900.000,00 EUR`, page 25, outlined above. Note which column: the 2022 figure, not the 185,5
sitting next to it.

## Why route instead of embedding everything

EU issuers file annual reports under ESEF, which is XHTML carrying Inline XBRL. The machine-readable
tag wraps the number a human reads, so the filing itself declares each figure's value, unit, period
and position.

A question about a tagged figure therefore has an exact answer at a known location. Putting that
through a vector search and asking a model to read it back is strictly worse: the answer can be
wrong, and the citation becomes a prediction. So those questions are looked up, and the citation is
the filer's own bounding box rather than an estimate.

Retrieval is used where retrieval belongs, on the narrative and qualitative content that carries no
tags.

## Results

Reproduce with `make eval`. Deterministic, seeded, no API key and no network.

**End to end**, 120 generated cases over three Austrian filings:

| Measure | n | Result |
|---|---|---|
| Routing accuracy, tagged figures | 60 | **0.983** |
| Answer exact match, tagged figures | 60 | **0.950** |
| Abstention recall, unanswerable questions | 60 | **1.000** |
| Abstention precision | 60 | **1.000** |
| False answer rate on unanswerable questions | 60 | **0.000** |
| Wrong-period traps survived | 30 | **1.000** |
| Latency p50 / p95 | 120 | **1.3 ms / 2.3 ms** |

Wrong-period traps ask for a real concept in a year the filing does not report. They separate knowing
the concept from knowing the period, which is the distinction a plausible wrong answer hides. The
system never returns a figure for one.

**Retrieval**, BM25 over 799 chunks, scored against bounding boxes taken from the filings' own tags:

| Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| 0.350 | 0.567 | 0.692 | 0.449 | 0.506 |

**Label quality**, the gold standard the above is measured against: 865 of 865 tagged facts located,
median IoU 0.947 between the tag's location and an independent text search for the same figure.

### Abstention is a chosen operating point, not a default

| Threshold | Exact match on answerable | False answer rate on unanswerable |
|---|---|---|
| 0.50 | 0.950 | 0.517 |
| 0.70 | 0.950 | 0.017 |
| **0.80** | **0.950** | **0.000** |

0.8 is the shipped setting. Exact match does not move because tagged figures come through the
structured layer at full confidence, so a passage-path threshold cannot affect them. What it does
cost is narrative recall, which this corpus has no gold set for, and that trade is deliberate: for a
document a reader has to verify, an answer they cannot check is worth less than none.

## How it works

```mermaid
flowchart LR
    Q["Question"] --> R{"Router"}

    R -->|"tagged concept<br/>+ period"| L["Fact ledger"]
    R -->|"otherwise"| P["Hybrid retrieval"]

    L --> LA["Exact value<br/>citation = the tag's own box"]
    P --> PA["Grounded answer<br/>with span citations"]

    LA --> G{"Supported?"}
    PA --> G
    G -->|yes| OUT["Answer + regions to outline"]
    G -->|no| ABS["Abstain, return nearest evidence"]

    classDef exact fill:#e6f4ea,stroke:#137333,color:#0b3d1c
    classDef soft fill:#fef7e0,stroke:#b06000,color:#5c3200
    class L,LA exact
    class P,PA soft
```

Ingestion runs alongside, offline: the filing is rendered to PDF, parsed into layout blocks that
keep their page geometry, and chunked so that each chunk carries the list of page regions it covers.
That list is what makes a citation resolvable to a region rather than to a passage, and it is a list
because a table can continue across a page break.

Gold labels come from a separate offline pass that reads the Inline XBRL and locates each tagged
figure by rendering the filing and reading back the PDF link annotations. Retrieval never sees those
tags: a test enforces that `ingest`, `retrieval` and `citation` cannot import the label plane, so the
benchmark cannot quietly measure itself.

Full design in [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md).

## Stack

Python 3.12, FastAPI, Pydantic, PyMuPDF for layout and rendering, lxml for Inline XBRL, BM25 built
in-repo, optional dense and hybrid retrieval via fastembed, Qdrant supported for larger corpora.
Docker, GitHub Actions, mypy strict, 159 tests.

Generation sits behind a protocol with an extractive implementation as the default, so the service
runs and the benchmark reproduces with no credentials. For a question whose answer is printed in the
document, quoting the sentence and outlining it is correct and cannot hallucinate.

Design decisions and their trade-offs are recorded in [docs/adr/](docs/adr/).

## Running it

```bash
make install                 # uv sync
make check                   # lint, typecheck, 159 tests

make labels                  # build the fact ledgers from data/filings
make eval                    # reproduce every number above
DISCLOSURE_RAG_CORPUS=data/ledgers make run    # API on :8000
```

Then:

```bash
curl -s localhost:8000/documents | jq

curl -s localhost:8000/query -H 'content-type: application/json' -d '{
  "question": "Wie hoch war Zinserträge unter Anwendung der Effektivzinsmethode im Geschäftsjahr 2022?",
  "document_id": "<id from /documents>"
}' | jq

# The regions from that response, rendered onto the page
curl -s "localhost:8000/page/<id>/25.png?regions=0.630,0.077,0.664,0.087" -o citation.png
```

Every response carries per-stage timings and a request id, and logs are structured JSON.

## Limitations

- **Three filings.** Enough for the benchmark to be meaningful, not enough to claim generality. The
  corpus is Austrian, so German-language; ESEF is EU-wide so the mechanics are not country-specific.
- **Retrieval quality is moderate.** Recall@10 of 0.692 on figure questions is a baseline, not a
  finished component. It matters less than it looks because those questions route to the structured
  layer, but it bounds the narrative path.
- **The narrative path has no gold set.** Building one needs human-confirmed question and answer
  pairs, so narrative answers are currently governed by abstention rather than measured.
- **Standard IFRS labels are not always bundled.** Issuers must label their own extension concepts
  but may reference the official taxonomy for the rest, so concept label coverage varies by filer.

## Licence

MIT. See [LICENSE](LICENSE).
