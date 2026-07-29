"""The serving plane must never be able to read a tag.

Principle P2 in the technical documentation. If the pipeline under test can see
the Inline XBRL, the benchmark measures nothing, and that failure would be
invisible in the results: every number would simply look very good.

The separation is architectural, so it is enforced by a test rather than by
remembering. This is a static check on imports, deliberately, because it fails
at review time rather than after a corpus has been rebuilt.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "disclosure_rag"
LABEL_PLANE = "disclosure_rag.labels"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _serving_plane_modules() -> list[Path]:
    return [path for path in SRC.rglob("*.py") if "labels" not in path.relative_to(SRC).parts]


def test_the_serving_plane_never_imports_the_label_plane() -> None:
    offenders = {
        str(path.relative_to(SRC)): sorted(
            name for name in _imports(path) if name.startswith(LABEL_PLANE)
        )
        for path in _serving_plane_modules()
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert not offenders, (
        f"serving-plane modules import the label plane: {offenders}. "
        "The oracle must not be reachable from the system under test."
    )


def test_the_check_covers_something() -> None:
    """Guards against the separation test passing because it found no files."""
    assert len(_serving_plane_modules()) >= 3


def test_the_label_plane_may_use_shared_provenance_types() -> None:
    """The contract in provenance.py is shared on purpose: it carries no tags."""
    imports = _imports(SRC / "labels" / "locate.py")
    assert "disclosure_rag.provenance" in imports
