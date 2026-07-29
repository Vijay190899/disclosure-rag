"""Dense retrieval, the second rung of the ablation ladder.

Embeddings come from fastembed, which runs ONNX rather than torch. That keeps
the install small enough that the evaluation stays reproducible on an ordinary
machine, which matters more here than the last point of accuracy: a benchmark
nobody can rerun is not much of a benchmark.

The model is multilingual because the corpus is German. An English-only
embedding model would measure its own language coverage rather than the value of
dense retrieval, which is the same mistake ADR-0009 caught in the question
generator.

Vectors are held in memory as a single matrix and searched by cosine similarity.
Qdrant is the right home for this once the corpus outgrows one machine, but at
843 chunks a matrix multiply is faster than a network round trip and has no
service to keep running.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from disclosure_rag.ingest.chunker import Chunk
from disclosure_rag.retrieval.base import ScoredChunk

if TYPE_CHECKING:
    import numpy as np

# Small and multilingual. Chosen for a reproducible baseline rather than for peak
# quality: intfloat/multilingual-e5-large scores better and is roughly five times
# the download, so it belongs in the ladder as its own row rather than as the
# default.
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Input token limits, measured rather than looked up. fastembed does not expose
# this, and it silently truncates, so getting it wrong costs real accuracy with
# no error to notice. Verified empirically: embedding a 100-word text and the
# same text plus 400 more words returns a cosine of exactly 1.0 for the MiniLM
# model, meaning the extra words were never seen.
MODEL_WINDOWS = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 128,
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": 128,
    "intfloat/multilingual-e5-large": 512,
}
DEFAULT_WINDOW = 512


class ChunkTooLongForModel(RuntimeError):
    """Raised when chunks exceed what the embedding model can read.

    This is a hard failure rather than a warning on purpose. It cost a full
    ablation run to find: chunks averaged 576 tokens against a 128-token window,
    dense retrieval scored 0.000, and nothing anywhere reported a problem. A
    silent 78% loss of every chunk is not something to leave discoverable only
    by suspicion.
    """


class DenseRetriever:
    """Cosine similarity over sentence embeddings."""

    def __init__(self, model_name: str = DEFAULT_MODEL, strict_window: bool = True) -> None:
        self.model_name = model_name
        self.name = f"dense:{model_name.rsplit('/', 1)[-1]}"
        self.window = MODEL_WINDOWS.get(model_name, DEFAULT_WINDOW)
        self.strict_window = strict_window
        self._chunks: list[Chunk] = []
        self._matrix: Any = None
        self._model: Any = None

    def _check_window(self, chunks: list[Chunk]) -> None:
        """Refuse to index chunks the model cannot read in full."""
        if not chunks or not self.strict_window:
            return
        oversized = [chunk for chunk in chunks if chunk.token_count > self.window]
        if not oversized:
            return
        worst = max(chunk.token_count for chunk in oversized)
        raise ChunkTooLongForModel(
            f"{len(oversized)} of {len(chunks)} chunks exceed the {self.window}-token "
            f"window of {self.model_name} (largest {worst}). The excess is silently "
            f"truncated, so retrieval would score against a fraction of each chunk. "
            f"Reduce the chunk budget below {self.window} tokens, or choose a model "
            f"with a longer window."
        )

    def _embedder(self) -> Any:  # noqa: ANN401 - fastembed ships no stubs
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def _encode(self, texts: list[str]) -> np.ndarray:
        import numpy as np

        vectors = np.asarray(list(self._embedder().embed(texts)), dtype="float32")
        # Normalise once so search is a plain dot product.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normalised: np.ndarray = vectors / np.maximum(norms, 1e-12)
        return normalised

    def index(self, chunks: list[Chunk]) -> None:
        self._check_window(chunks)
        self._chunks = list(chunks)
        self._matrix = self._encode([chunk.text for chunk in self._chunks]) if chunks else None

    def search(
        self, query: str, top_k: int = 10, document_id: str | None = None
    ) -> list[ScoredChunk]:
        if self._matrix is None or not self._chunks:
            return []
        import numpy as np

        scores = self._matrix @ self._encode([query])[0]
        if document_id is not None:
            mask = np.array(
                [chunk.document_id == document_id for chunk in self._chunks], dtype=bool
            )
            scores = np.where(mask, scores, -np.inf)
        # Ties broken by position, so a rerun ranks identically.
        order = np.lexsort((np.arange(len(scores)), -scores))[:top_k]
        return [
            ScoredChunk(chunk=self._chunks[int(position)], score=float(scores[int(position)]))
            for position in order
            if np.isfinite(scores[int(position)])
        ]
