"""Retrieval must never be able to read the tags it is measured against.

The benchmark's honesty rests on this. Gold citation boxes come from the filer's
Inline XBRL; if the retriever could see them, every retrieval number would be
meaningless and the failure would be invisible, because the results would simply
look excellent.

The rule is narrower than "the product must not read structured data", which
would be wrong. ESEF filings genuinely carry these tags, so a production system
reads them and answers tagged figures exactly rather than guessing. That is the
point of the routing design. What must stay clean is the part being scored.

Specified as an allowlist of modules that must not touch the label plane, rather
than as a list of exemptions, so a new module cannot become exempt by default.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "disclosure_rag"
LABEL_PLANE = "disclosure_rag.labels"

# Everything scored by the retrieval benchmark. These may not import the labels.
UNDER_TEST = ("ingest", "retrieval", "citation.py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _modules_under_test() -> list[Path]:
    paths: list[Path] = []
    for entry in UNDER_TEST:
        target = SRC / entry
        if target.is_dir():
            paths.extend(sorted(target.rglob("*.py")))
        elif target.exists():
            paths.append(target)
    return paths


def test_retrieval_and_ingest_never_import_the_label_plane() -> None:
    offenders = {
        str(path.relative_to(SRC)).replace("\\", "/"): sorted(
            name for name in _imports(path) if name.startswith(LABEL_PLANE)
        )
        for path in _modules_under_test()
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert not offenders, (
        f"modules scored by the retrieval benchmark import the label plane: {offenders}. "
        "The answer key must not be reachable from the system under test."
    )


def test_the_allowlist_resolves_to_real_files() -> None:
    """Guards against the check passing because it found nothing to check."""
    found = {str(path.relative_to(SRC)).replace("\\", "/") for path in _modules_under_test()}
    assert "ingest/blocks.py" in found
    assert "ingest/chunker.py" in found
    assert "retrieval/lexical.py" in found
    assert "retrieval/dense.py" in found
    assert "citation.py" in found


def test_the_answer_pipeline_does_read_the_ledger() -> None:
    """Stated positively: routing tagged figures to the structured layer is the design.

    A tagged figure has an exact value and an exact location, so looking it up
    beats asking a model to read it back out of a passage. The citation is then
    the filer's own tag rather than a prediction.
    """
    imports = _imports(SRC / "answer" / "pipeline.py")
    assert any(name.startswith(LABEL_PLANE) for name in imports)


def test_the_evaluation_harness_reads_both_sides() -> None:
    """It holds the answer key in one hand and the predictions in the other."""
    imports = _imports(SRC / "evaluation" / "questions.py")
    assert any(name.startswith(LABEL_PLANE) for name in imports)
