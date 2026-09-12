"""M9 (phase 2 Wave 0) exit criteria, as tests (plan-phase-2.md §5.2).

Owned by the lead, same reasoning as `test_m0_contract.py`: Wave 1+ agents
should not need to touch this file; if one of these fails, a frozen contract
has been edited without an amendment.
"""

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_MD = REPO_ROOT / "CONTRACTS.md"

FROZEN_HEADER = "# FROZEN"

#: Every file this wave freezes or re-freezes (plan-phase-2.md §5.1),
#: excluding the phase-1 files `test_m0_contract.py` already covers.
NEW_FROZEN_MODULES = [
    "ra2/domain/codes.py",
    "ra2/domain/codelist_coverage.py",
    "ra2/domain/feature.py",
    "ra2/domain/fingerprint.py",
]

#: Amended, already covered by `test_m0_contract.py`'s header/listing checks —
#: just re-asserted here so a Wave 0 diff that drops the header is caught
#: locally, without cross-referencing the other file.
AMENDED_FROZEN_MODULES = [
    "ra2/domain/ids.py",
    "ra2/persistence/models.py",
    "ra2/services/protocols.py",
    "ra2/services/container.py",
    "ra2/services/errors.py",
    "ra2/services/readmodels.py",
    "ra2/api/schemas.py",
    "ra2/api/deps.py",
    "ra2/api/v1/router.py",
    "ra2/infra/config.py",
    "ra2/main.py",
]

#: New, not frozen — a body is expected from Wave 1+ (plan-phase-2.md §6).
NEW_STUB_MODULES = [
    "ra2/services/codelist_service.py",
    "ra2/services/feature_service.py",
    "ra2/api/v1/codelists.py",
    "ra2/api/v1/features.py",
    "ra2/ui/components/derivation_builder.py",
    "ra2/ui/components/feature_sets_table.py",
]


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + AMENDED_FROZEN_MODULES)
def test_frozen_module_carries_the_header(relative_path):
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} is missing"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith(FROZEN_HEADER), (
        f"{relative_path} must start with '{FROZEN_HEADER}...' — see CONTRACTS.md"
    )
    assert "CONTRACTS.md" in first_line


@pytest.mark.parametrize("relative_path", NEW_STUB_MODULES)
def test_stub_module_carries_the_header(relative_path):
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} is missing"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# STUB"), f"{relative_path} must start with '# STUB...'"


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + NEW_STUB_MODULES)
def test_contracts_md_lists_every_new_file(relative_path):
    text = CONTRACTS_MD.read_text(encoding="utf-8")
    assert relative_path in text, f"CONTRACTS.md does not list {relative_path}"


@pytest.mark.parametrize("relative_path", NEW_FROZEN_MODULES + NEW_STUB_MODULES)
def test_every_new_module_imports(relative_path):
    module = relative_path.removesuffix(".py").replace("/", ".")
    imported = importlib.import_module(module)
    for name in getattr(imported, "__all__", ()):
        assert hasattr(imported, name), f"{module}.__all__ names a missing {name}"


def test_claude_md_names_both_migration_authors():
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "A3 for phase 1" in text
    assert "D3 for phase 2" in text


def test_alembic_chain_reaches_the_phase_2_stub_revision():
    """The migration D3 fills in is already wired into the chain, not
    orphaned (plan-phase-2.md §5.2: `alembic upgrade head` must run clean)."""
    versions_dir = REPO_ROOT / "ra2/persistence/migrations/versions"
    stub_revisions = [
        p for p in versions_dir.glob("*.py") if "phase_2_codelists_and_features" in p.name
    ]
    assert len(stub_revisions) == 1
    text = stub_revisions[0].read_text(encoding="utf-8")
    assert 'down_revision: str | None = "a39c30e4559d"' in text


def test_services_bundle_has_the_two_new_fields(app_factory):
    """A fresh `create_app()` still builds; `Services` has two more fields,
    both satisfiable by the new stub classes (plan-phase-2.md §5.2)."""
    app = app_factory(mount_ui=False)
    services = app.state.services
    assert services.codelist is not None
    assert services.feature is not None
