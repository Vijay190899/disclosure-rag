"""Identify exactly which corpus and configuration produced an answer.

A citation that cannot be reproduced against a known version of the document is
not evidence, it is a screenshot. Filings get amended and restated, indexes get
rebuilt with different chunking, and models get swapped, so "page 25, region
(0.63, 0.08)" means nothing six months later unless the thing it pointed into is
identified.

Two identifiers do that work.

A **document version** is the hash of the source filing. Two builds of the same
filing produce the same version; an amended filing produces a different one, and
nothing has to remember to bump anything.

A **snapshot id** is the hash of every document version in the corpus together
with the settings that decide what the index contains. Change a filing, add one,
or rechunk, and the snapshot changes, because all three change what an answer
would be.

Both are derived rather than assigned. An identifier a human maintains is one
that eventually lies.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field

# Bumped when a change alters answers for an unchanged corpus, so a stored
# record is never replayed against a pipeline that would answer differently.
PIPELINE_VERSION = "1.0.0"

_CHUNK = 1024 * 1024


def hash_file(path: Path) -> str:
    """Content hash of a file, streamed so a large filing is not held in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IndexSettings(BaseModel):
    """Everything about how the index was built that changes what it returns."""

    model_config = {"frozen": True}

    chunk_tokens: int
    overlap_tokens: int
    retriever: str

    def fingerprint(self) -> str:
        return hash_text(f"{self.chunk_tokens}:{self.overlap_tokens}:{self.retriever}")


class Snapshot(BaseModel):
    """The corpus and configuration an answer was produced against."""

    model_config = {"frozen": True}

    snapshot_id: str
    pipeline_version: str = PIPELINE_VERSION
    documents: dict[str, str] = Field(
        default_factory=dict, description="document id to its source content hash"
    )
    settings: IndexSettings

    @classmethod
    def build(cls, documents: dict[str, str], settings: IndexSettings) -> Snapshot:
        """Derive the snapshot id from the corpus and the settings.

        Documents are sorted, so the id does not depend on the order the corpus
        happened to load in. That matters: an id that changes when nothing did
        makes every stored record look stale and teaches people to ignore it.
        """
        material = ";".join(f"{key}={documents[key]}" for key in sorted(documents))
        combined = f"{PIPELINE_VERSION}|{settings.fingerprint()}|{material}"
        return cls(
            snapshot_id=hash_text(combined)[:16],
            documents=dict(sorted(documents.items())),
            settings=settings,
        )

    def covers(self, document_id: str) -> bool:
        return document_id in self.documents

    def version_of(self, document_id: str) -> str:
        return self.documents.get(document_id, "")


def label_plane_version() -> str:
    """Content hash of the code that builds a fact ledger.

    Derived rather than assigned, for the same reason document versions are: a
    number a person remembers to bump is one that eventually does not get
    bumped, and the failure is silent. Sorted before hashing so file iteration
    order cannot move it.
    """
    directory = Path(__file__).parent / "labels"
    sources = sorted(path.read_text(encoding="utf-8") for path in directory.glob("*.py"))
    return hash_text("\n".join(sources))
