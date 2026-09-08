"""`ra2/infra/files.py` is the only place in the app that opens a file
(sw-design.md §2, N4; CLAUDE.md Do-NOT #4).

AST-based, like `tests/test_m0_contract.py`'s other structural checks, so a
docstring or comment mentioning `open(` cannot produce a false positive and a
disguised call site (`getattr(obj, "open")(...)`) is out of scope on purpose
— this catches the call shapes anyone would actually write.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.backend

REPO_ROOT = Path(__file__).resolve().parents[3]
RA2_ROOT = REPO_ROOT / "ra2"
CHOKEPOINT = RA2_ROOT / "infra" / "files.py"


def _open_call_lines(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_open = (isinstance(func, ast.Name) and func.id == "open") or (
            isinstance(func, ast.Attribute) and func.attr == "open"
        )
        if is_open:
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return offenders


def test_chokepoint_file_exists_and_is_the_only_one_that_opens() -> None:
    assert CHOKEPOINT.exists()

    offenders = [
        line
        for path in sorted(RA2_ROOT.rglob("*.py"))
        if path != CHOKEPOINT
        for line in _open_call_lines(path)
    ]
    assert offenders == [], f"open() called outside infra/files.py: {offenders}"


def test_chokepoint_file_itself_does_call_open() -> None:
    """A sanity check on the checker above: it is not vacuously green."""
    assert _open_call_lines(CHOKEPOINT) != []
