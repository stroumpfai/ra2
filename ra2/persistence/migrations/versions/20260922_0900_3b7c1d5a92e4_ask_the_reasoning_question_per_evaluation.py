"""ask the reasoning question per evaluation

Revision ID: 3b7c1d5a92e4
Revises: 090e7fdc12c5
Create Date: 2026-09-22 09:00:00.000000+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`evaluation.reasoning_effort` — step 5's third control, beside temperature and
seed. `090e7fdc12c5` pinned the effort on the **run** so two runs that asked
different questions could not record identical provenance (mvp-spec.md §19.8).
It left the choice in the environment, which made the comparison that column
exists for — "set `high` and launch a second evaluation" — a matter of editing
`RA2_LLM_REASONING_EFFORT` and restarting the app between two evaluations that
are meant to be comparable. A pinned input the analyst is expected to vary
between evaluations is a column on `evaluation`
(`plan-evaluation-view-improvements.md` §5).

**NOT NULL, backfilled `none` — unlike the run column, which is nullable with
no backfill.** The difference is not a preference. A `run` written before that
revision genuinely does not know what effort it asked with, and inventing one
would be inventing provenance. An `evaluation` is a *setup*: every row that
existed before this column ran under the process default, and the default has
been `none` since it existed, so `none` is a fact about those rows rather than
a guess about them.

`server_default="none"` on add, and **kept**: the rebuild backfills every
existing row in the same statement, and dropping the default afterwards would
cost a second full table copy to remove something that matches the model's own
default. A server default that agrees with the mapper is not a second source
of truth.

`batch_alter_table` because the target is SQLite, which has no full
`ALTER TABLE`; alembic rebuilds and copies.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b7c1d5a92e4"
down_revision: str | None = "090e7fdc12c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "reasoning_effort",
                sa.String(length=16),
                nullable=False,
                server_default="none",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.drop_column("reasoning_effort")
