"""Alembic migrations: apply cleanly, never drift from
`ra2.persistence.models.Base.metadata`, and form a single linear chain
(sw-design.md §11.2, §12.10, plan-m0-m5.md X3)."""

import ast
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine

from ra2.infra.config import Settings
from ra2.persistence.models import Base

pytestmark = pytest.mark.backend

REPO_ROOT = Path(__file__).resolve().parents[3]


async def test_upgrade_head_creates_every_table(migrated_engine: AsyncEngine) -> None:
    """`alembic upgrade head` against a real temp-file SQLite database
    (never `:memory:`) produces every table `models.py` declares."""
    async with migrated_engine.connect() as conn:
        table_names = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())

    expected = set(Base.metadata.tables) - {"alembic_version"}
    assert expected.issubset(set(table_names))
    assert "alembic_version" in table_names


async def test_alembic_check_reports_no_drift(
    migrated_engine: AsyncEngine, run_upgrade_head: Settings
) -> None:
    """The migration and `models.py` agree exactly — no autogenerate diff.

    This is the programmatic equivalent of `alembic check`: it fails the same
    way `alembic check` would if a column, constraint or index in `models.py`
    had no matching operation in the migration, or vice versa.
    """

    def _diff(sync_conn: sa.Connection) -> list[object]:
        context = MigrationContext.configure(
            sync_conn,
            opts={"compare_type": True, "compare_server_default": True},
        )
        return list(compare_metadata(context, Base.metadata))

    async with migrated_engine.connect() as conn:
        diff = await conn.run_sync(_diff)

    assert diff == [], f"models.py and the migration have drifted: {diff!r}"


def test_migrations_form_a_single_linear_chain(alembic_config: Config) -> None:
    """One migration **author** (plan-m0-m5.md X3) means one linear history —
    never two branch heads from independently-generated revisions racing each
    other. It does not mean the schema is forever frozen at one revision: a
    real bug found after the initial migration lands gets a new revision on
    top, same as any other schema change (§12.3 — never edit an *applied* one,
    add a new one instead)."""
    script = ScriptDirectory.from_config(alembic_config)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected exactly one migration head, found {heads}"


def test_exactly_one_migration_is_the_root(alembic_config: Config) -> None:
    """Exactly one revision has no parent — the original schema's migration.
    Every other revision chains onto something, so the history is a single
    line from that root to the current head, not a hand-edited fork."""
    script = ScriptDirectory.from_config(alembic_config)
    roots = [rev.revision for rev in script.walk_revisions() if rev.down_revision is None]
    assert len(roots) == 1, f"expected exactly one root revision, found {roots}"


def test_no_metadata_create_all_in_persistence_or_tests() -> None:
    """§12.10: `metadata.create_all()` is never *called* anywhere.

    Matched on the AST, the same way `tests/test_m0_contract.py`'s
    project-wide `test_no_metadata_create_all_anywhere` does — a plain text
    grep for `create_all` also hits `session.py`'s and `models.py`'s own
    docstrings *stating* the rule, which would make the gate permanently red
    on frozen files A3 cannot edit. Scoped here to what this branch owns;
    the frozen test covers every file under `ra2/` and `tests/`.
    """
    offenders = []
    for root in ("ra2/persistence", "tests/backend"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "create_all"
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == []
