"""phase 2: codelists and features (stub)

Revision ID: 4995824acfe4
Revises: a39c30e4559d
Create Date: 2026-09-12 00:00:00.000000+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

**Empty on purpose.** M9 (Wave 0) wires this revision into the chain so
`alembic upgrade head` has somewhere to land and D3's Wave 1 work is "fill
this in," not "create the first phase-2 revision from nothing" (CLAUDE.md:
D3 is phase 2's one migration author, ever; plan-phase-2.md §7 D3). The real
`upgrade()`/`downgrade()` bodies — `code_table_import`, `code_attribute`,
`code_value`, `column_mapping`, `feature_config`, `feature`, and the
`evaluation.feature_config_id` FK change — are D3's.
"""

from collections.abc import Sequence

revision: str = "4995824acfe4"
down_revision: str | None = "a39c30e4559d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
