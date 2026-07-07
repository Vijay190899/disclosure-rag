# FinRAG, a compliance copilot for financial documents

Compliance work involves a lot of slow manual reading. Someone sits down with a 200-page annual report or a BaFin filing and checks whether the numbers in a table match the claims in the text, whether a required disclosure is actually present, and where exactly it lives in the document. It's tedious and easy to get wrong. Retrieval systems should be good at this, but most RAG demos fall over the moment you hand them a real financial PDF full of nested tables and footnotes.

I'm building FinRAG to see how far a retrieval pipeline can go when it actually respects document structure and cites its answers down to the page and the region, instead of pointing at a vague chunk.

## What it does

- Parses financial PDFs while keeping tables and layout intact, instead of flattening everything into plain text.
- Answers questions and cites the exact page and region each claim came from, so a person can verify in one click.
- Checks its own answers with a second LLM pass before returning them, and flags low-confidence answers instead of guessing.
- Runs as an API, not a notebook.

## Why I made these choices

- Layout-aware parsing (LlamaParse / ColPali). Plain PDF-to-text throws away table structure, which is the one thing that matters most in financial documents.
- Hybrid retrieval (dense plus BM25) with reranking. Dense vectors miss exact figures and ticker symbols; lexical search catches them. Reranking cleans up the merged list.
- Qdrant for vectors, because it does hybrid natively and runs locally during development.
- Self-checking instead of blind trust. In compliance, a confident wrong answer is worse than "I'm not sure", so there's a judge step and every answer carries its sources.
- OpenAI Agents SDK for the answer loop (plan, retrieve, self-check). It's lightweight and tool-centric, which fits a single focused agent. The retrieval layer is exposed as an MCP server so the agent, or anything else that speaks MCP, can call it as a tool.

## Stack

Full detail in [docs/STACK.md](docs/STACK.md); architecture and design in [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md). Short version: Python, FastAPI, Qdrant, LlamaParse/ColPali, hybrid search with Cohere reranking, OpenAI Agents SDK, MCP, Ragas for evaluation, Docker, deployed on AWS.

## Status

Work in progress. I'm building this in the open. Rough state of things:

- [ ] Ingestion and layout-aware parsing
- [ ] Hybrid retrieval and reranking
- [ ] Self-correcting answer agent with citations
- [ ] MCP retrieval server
- [ ] Ragas evaluation harness and baseline numbers
- [ ] FastAPI service and Docker
- [ ] AWS deployment and a thin citation-viewer UI

I'll keep the checkboxes honest as I go. Decisions I make along the way live in [DECISIONS.md](DECISIONS.md).

## Running it locally

```bash
make install          # sets up the environment with uv
cp .env.example .env  # then fill in your keys
make test
make run              # starts the API on http://localhost:8000
```

## Licence

MIT. See [LICENSE](LICENSE).
