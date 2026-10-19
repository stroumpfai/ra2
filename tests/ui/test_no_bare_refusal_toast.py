"""Layer 3 — no view toasts `str(exc)` (plan-refusal-messages.md D3).

`FeatureValidationError` stringifies to a count; `refusal_text` is what puts
its sentences on screen. A bare `ui.notify(str(exc))` is how thirty-six
handlers came to show "1 feature validation error(s)".
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui

_UI = Path(__file__).resolve().parents[2] / "ra2" / "ui"


def _is_bare_str_toast(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "notify"
        and bool(node.args)
        and isinstance(node.args[0], ast.Call)
        and isinstance(node.args[0].func, ast.Name)
        and node.args[0].func.id == "str"
    )


def test_no_view_toasts_str_of_an_exception() -> None:
    offenders = [
        f"{path.relative_to(_UI.parent.parent)}:{node.lineno}"
        for path in sorted(_UI.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if _is_bare_str_toast(node)
    ]
    assert not offenders, f"use refusal_text(exc): {offenders}"
