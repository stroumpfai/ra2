"""keep an evaluation

Revision ID: 3ce2190bd859
Revises: b4f2c81e6d37
Create Date: 2026-10-17 12:00:00.000000+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`evaluation.kept_at`: an analyst marked this evaluation to keep (sw-design.md
SD61). A kept evaluation, and every run of it, is refused by discard until it
is released: G3 in §18.2.

**Nullable, and no backfill.** `NULL` is "nobody marked it", which is true of
every evaluation that exists before this revision. Nothing is guessed, and no
existing row is touched.

`batch_alter_table` because the target is SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3ce2190bd859"
down_revision: str | None = "b4f2c81e6d37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kept_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.drop_column("kept_at")
