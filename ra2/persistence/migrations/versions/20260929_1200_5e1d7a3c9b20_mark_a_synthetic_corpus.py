"""mark a synthetic corpus

Revision ID: 5e1d7a3c9b20
Revises: ccbae1b96d1b
Create Date: 2026-09-29 12:00:00.000000+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`corpus.is_synthetic`: the corpus was built from invented data (sw-design.md
SD45, risk D8). `is_dev_sized` is a size threshold, so `just reset-seed yes
--records 3000` produced a corpus that looked like a real one on every screen.

**NOT NULL, `server_default="0"`, and no backfill.** Every corpus that
exists before this revision reads as *not* synthetic. That is a choice, not a
fact about those rows. Marking them from their keys would be an `UPDATE
corpus`, and Do-NOT #2 does not bend for a migration. The default errs the
safe way: a seed corpus left over from before reads as real, so `just reset`
asks for its second token once, and its ranking still names a leader until it
is re-seeded. A corpus frozen after this revision is marked at freeze.

`server_default` is kept, for `3b7c1d5a92e4`'s reason, and declared on the
mapper too so `alembic check` sees no drift. `batch_alter_table` because the
target is SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e1d7a3c9b20"
down_revision: str | None = "ccbae1b96d1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("corpus", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("corpus", schema=None) as batch_op:
        batch_op.drop_column("is_synthetic")
