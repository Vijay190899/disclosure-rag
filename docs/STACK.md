# Stack

A running list of what this project uses and why. I'd rather explain the reasoning than just dump a dependency list.

## Language and runtime
- **Python 3.12**, the default for anything LLM-adjacent.
- **uv** for packaging and virtualenvs. It's fast, and it's become the sensible default.

## Serving
- **FastAPI** with async endpoints. The ingestion and retrieval calls are I/O-bound, so async earns its keep here.
- **Uvicorn** as the ASGI server.
- **Pydantic / pydantic-settings** for request models and config.

## Retrieval
- **Qdrant** for the vector store. It supports hybrid (dense plus sparse) natively and runs in a local container during development.
- **LlamaParse / ColPali** for layout-aware parsing, so tables and page geometry survive ingestion.
- **BM25** for sparse lexical retrieval, merged with dense results. Exact figures and codes need lexical matching.
- **Cohere Rerank** (cross-encoder) reranks the merged candidate set before it reaches the LLM.
- Parent-child (hierarchical) chunking, so a retrieved snippet can pull its surrounding context.

## Agent and tooling
- **OpenAI Agents SDK** for the answer loop (plan, retrieve, self-check). Deliberately lightweight for a single-agent task.
- **MCP (Model Context Protocol)**: the retrieval layer is exposed as an MCP server so any MCP-aware client can use it as a tool.

## Evaluation
- **Ragas** for retrieval hit-rate and faithfulness. CI fails if these regress.
- LLM-as-a-judge for answer-level self-correction and confidence scoring.

## Ops and deployment
- **Docker** for local parity.
- **AWS**: documents in S3, service on ECS/EKS. (Bedrock is an option for a managed-model path.)
- **GitHub Actions**: lint, test, and run the eval as a regression gate.

## Frontend
- A thin citation viewer (Streamlit first for speed, Next.js later if I want the TypeScript surface).

## Deliberately out of scope for now
- Fine-tuning, which a separate project covers. Here the retrieval and grounding are the interesting part.
