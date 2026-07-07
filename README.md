# FinRAG — a compliance copilot for financial documents

I kept coming back to the same problem while reading about how compliance teams actually work: someone has to sit down with a 200-page annual report or a BaFin filing and check whether the numbers in a table line up with the claims in the text, whether a required disclosure is even present, and *where* exactly it lives. It's slow, it's easy to get wrong, and it's the sort of task retrieval systems should be great at — except most RAG demos quietly fall apart the moment you hand them a real financial PDF full of nested tables and footnotes.

So I'm building FinRAG to see how far a retrieval pipeline can go when it actually respects document structure and cites its answers down to the page and the bounding box, instead of hand-waving with a vague chunk.

## What it does

- Parses financial PDFs while preserving tables and layout, instead of flattening everything into a wall of text.
- Answers questions about the documents and **cites the exact page and region** each claim came from, so a human can verify in one click.
- Checks its own answers with an LLM-as-a-judge pass before returning them, and flags low-confidence responses instead of bluffing.
- Ships as an API you can actually call, not a notebook.

## Why I made the choices I did

- **Layout-aware parsing (LlamaParse / ColPali).** Naive PDF-to-text destroys the one thing that matters in financial docs — the table structure. Keeping geometry is the whole point.
- **Hybrid retrieval (dense + BM25) with reranking.** Dense vectors miss exact figures and ticker symbols; lexical search catches them. Reranking cleans up the merged list. Numbers matter here, so I'm not relying on embeddings alone.
- **Qdrant** for vectors because it does hybrid natively and runs locally for dev.
- **Self-correction over blind trust.** In a compliance setting a confident wrong answer is worse than "I'm not sure" — so there's a judge step and every answer carries its sources.
- **OpenAI Agents SDK** for the answer loop (plan → retrieve → self-check). It's lightweight and tool-centric, which is the right weight for a single focused agent; the retrieval layer is exposed as an MCP server so the agent (or anything else that speaks MCP) can call it as a tool.

## Stack

Full detail in [docs/STACK.md](docs/STACK.md); architecture and design in [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md). Short version: Python, FastAPI, Qdrant, LlamaParse/ColPali, hybrid search + Cohere reranking, OpenAI Agents SDK, MCP, Ragas for eval, Docker, deployed on AWS.

## Status

Work in progress — I'm building this in the open. Rough state of things:

- [ ] Ingestion + layout-aware parsing
- [ ] Hybrid retrieval + reranking
- [ ] Self-correcting answer agent with citations
- [ ] MCP retrieval server
- [ ] Ragas evaluation harness + baseline numbers
- [ ] FastAPI service + Docker
- [ ] AWS deployment + thin citation-viewer UI

I'll keep the checkboxes honest as I go. Decisions I make along the way live in [DECISIONS.md](DECISIONS.md).

## Running it locally

```bash
make install     # sets up the environment with uv
cp .env.example .env   # then fill in your keys
make test
make run         # starts the API on http://localhost:8000
```

## Licence

MIT — see [LICENSE](LICENSE).
