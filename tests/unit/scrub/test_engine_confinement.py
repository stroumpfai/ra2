"""`regex` is imported by `ra2/domain/scrub.py` and nowhere else (`SD66`).

`.importlinter`'s `regex-only-in-the-scrubber` contract says the same for
static imports. This reads the AST of every module in `ra2/`, and catches
`importlib.import_module("regex")` and `__import__("regex")` too, which a
linter contract does not see — the same arrangement `openai` and `pynvml`
have in `tests/test_p3_contract.py`.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

RA2 = Path(__file__).resolve().parents[3] / "ra2"
ALLOWED = {"ra2/domain/scrub.py"}


def _names_regex(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "regex" or alias.name.startswith("regex.") for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "regex" or node.module.startswith("regex."))
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "regex"
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            )
        ):
            return True
    return False


def test_only_the_scrubber_imports_regex() -> None:
    importers = {
        path.relative_to(RA2.parent).as_posix()
        for path in RA2.rglob("*.py")
        if _names_regex(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert importers == ALLOWED


def test_the_contract_is_declared_for_the_linter_as_well() -> None:
    text = (RA2.parent / ".importlinter").read_text(encoding="utf-8")
    assert "[importlinter:contract:regex-only-in-the-scrubber]" in text
    assert "ra2.domain.scrub -> regex" in text
