"""M0 exit criteria, as tests (plan-m0-m5.md §3.2).

Owned by the lead. Wave 1-3 agents should not need to touch this file; if one
of these fails, a frozen contract has been edited without an amendment.
"""

import ast
import importlib
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_MD = REPO_ROOT / "CONTRACTS.md"

FROZEN_HEADER = "# FROZEN"

#: Every file plan-m0-m5.md §3.1 freezes, plus the additions M0 introduces.
#: CONTRACTS.md is the human-readable version of this list.
FROZEN_MODULES = [
    "ra2/domain/ids.py",
    "ra2/domain/findings.py",
    "ra2/domain/delivery.py",
    "ra2/domain/census.py",
    "ra2/domain/language.py",
    "ra2/domain/llm.py",
    "ra2/infra/config.py",
    "ra2/infra/clock.py",
    "ra2/infra/idgen.py",
    "ra2/infra/tasks.py",
    "ra2/infra/filestore.py",
    "ra2/persistence/models.py",
    "ra2/persistence/session.py",
    "ra2/persistence/migrations/env.py",
    "ra2/services/errors.py",
    "ra2/services/readmodels.py",
    "ra2/services/protocols.py",
    "ra2/services/container.py",
    "ra2/services/delivery_service.py",
    "ra2/services/corpus_service.py",
    "ra2/services/census_service.py",
    "ra2/services/export_service.py",
    "ra2/api/schemas.py",
    "ra2/api/deps.py",
    "ra2/api/v1/router.py",
    "ra2/main.py",
    "tests/conftest.py",
]

NAV_ROUTES = [
    "/import",
    "/census",
    "/codelists",
    "/features",
    "/evaluation",
    "/results",
    "/mismatches",
]


@pytest.mark.parametrize("relative_path", FROZEN_MODULES)
def test_frozen_module_carries_the_header(relative_path):
    """Every frozen module says so on its first line."""
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} is missing"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith(FROZEN_HEADER), (
        f"{relative_path} must start with '{FROZEN_HEADER} — see CONTRACTS.md'"
    )
    assert "CONTRACTS.md" in first_line


@pytest.mark.parametrize("relative_path", FROZEN_MODULES)
def test_contracts_md_lists_every_frozen_file(relative_path):
    """No agent has to guess what is frozen."""
    text = CONTRACTS_MD.read_text(encoding="utf-8")
    assert relative_path in text, f"CONTRACTS.md does not list {relative_path}"


def test_claude_md_carries_the_do_not_list():
    """CLAUDE.md moves from M8 into M0 (E3): sub-agents read it."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for phrase in (
        "openai",
        "metadata.create_all",
        'errors="replace"',
        "app.storage.client",
        "sw-design.md",
    ):
        assert phrase in text, f"CLAUDE.md is missing the invariant mentioning {phrase!r}"
    # The twelve Do-NOT items of sw-design.md §12, numbered.
    assert len(re.findall(r"^\d+\. \*\*Never\*\*", text, flags=re.MULTILINE)) == 12


def test_no_errors_replace_anywhere():
    """§12.4 / mvp-spec.md §4.2.1: undecodable bytes fail the file.

    A1 owns the parser; this guard exists from M0 so the rule cannot be broken
    quietly in the meantime. Matched on the **parsed call**, not on the text,
    so a docstring may name the rule it is stating.
    """
    offenders = [
        f"{path}:{node.lineno}"
        for path, tree in _parsed_sources()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "errors" and isinstance(kw.value, ast.Constant) and kw.value.value == "replace"
    ]
    assert offenders == []


def test_no_metadata_create_all_anywhere():
    """§12.10: the schema comes from `alembic upgrade head`, always."""
    offenders = [
        f"{path}:{node.lineno}"
        for path, tree in _parsed_sources()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_all"
    ]
    assert offenders == []


def _parsed_sources() -> list[tuple[Path, ast.Module]]:
    """Every `.py` under `ra2/` and `tests/`, parsed."""
    return [
        (path.relative_to(REPO_ROOT), ast.parse(path.read_text(encoding="utf-8")))
        for root in ("ra2", "tests")
        for path in sorted((REPO_ROOT / root).rglob("*.py"))
    ]


#: `migrations/env.py` runs migrations as a side effect of import, and
#: `tests/conftest.py` is already imported by pytest itself.
NOT_IMPORTABLE_IN_ISOLATION = {
    "ra2/persistence/migrations/env.py",
    "tests/conftest.py",
}


@pytest.mark.parametrize(
    "relative_path",
    [p for p in FROZEN_MODULES if p not in NOT_IMPORTABLE_IN_ISOLATION],
)
def test_every_frozen_module_imports(relative_path):
    """A frozen module that no longer imports has been broken by someone."""
    module = relative_path.removesuffix(".py").replace("/", ".")
    assert importlib.import_module(module) is not None


def _every_ra2_module() -> list[str]:
    """Every module under `ra2/`, except the Alembic env, which runs
    migrations as a side effect of being imported."""
    return sorted(
        path.relative_to(REPO_ROOT)
        .as_posix()
        .removesuffix("/__init__.py")
        .removesuffix(".py")
        .replace("/", ".")
        for path in (REPO_ROOT / "ra2").rglob("*.py")
        if "migrations" not in path.parts
    )


@pytest.mark.parametrize("module", _every_ra2_module())
def test_every_module_imports(module):
    """Nothing in `ra2/` has an import error, a cycle or a typo in `__all__`.

    Cheap, and it means a Wave 1 agent finds out about a broken import from
    its own `just test` rather than from the lead at integration.
    """
    imported = importlib.import_module(module)
    for name in getattr(imported, "__all__", ()):
        assert hasattr(imported, name), f"{module}.__all__ names a missing {name}"


def test_create_app_registers_the_seven_nav_routes_and_the_api(app_factory):
    """The M0 exit criterion, verbatim."""
    app = app_factory(mount_ui=True)

    paths = {getattr(route, "path", None) for route in _walk(app.routes)}
    for route in NAV_ROUTES:
        assert route in paths, f"nav route {route} is not registered"

    api_paths = sorted(app.openapi()["paths"])
    assert any(p.startswith("/api/v1/deliveries") for p in api_paths)
    assert any(p.startswith("/api/v1/corpora") for p in api_paths)
    assert any(p.startswith("/api/v1/census") for p in api_paths)
    assert any(p.startswith("/api/v1/tasks") for p in api_paths)


def _walk(routes: Iterable[object]) -> Iterator[object]:
    """Starlette/NiceGUI nest routers and mounts; flatten them."""
    for route in routes:
        nested = getattr(route, "routes", None)
        sub_app = getattr(route, "app", None)
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _walk(original.routes)
        elif nested is not None:
            yield from _walk(nested)
        elif sub_app is not None and hasattr(sub_app, "routes"):
            yield from _walk(sub_app.routes)
        else:
            yield route
