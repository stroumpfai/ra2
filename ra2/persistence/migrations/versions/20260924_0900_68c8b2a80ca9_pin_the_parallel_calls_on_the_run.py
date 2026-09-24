"""pin the parallel calls on the run

Revision ID: 68c8b2a80ca9
Revises: 3b7c1d5a92e4
Create Date: 2026-09-24 09:00:00.000000+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`run.llm_parallel_calls` — the records this run keeps in flight, pinned at
launch from `RA2_LLM_PARALLEL_CALLS[model tag]` (sw-design.md §15.4, SD38).
Resume executes at the pin, and the ranking divides mean latency by it, so it
is provenance, not a log line.

**NOT NULL, backfilled `1`**, where `090e7fdc12c5`'s `llm_reasoning_effort` is
nullable with no backfill. That column's rows genuinely did not record what
they asked. These rows did record this, in effect: no code before this
revision could put two records of one run in flight, so every existing run
executed at 1. The backfill is a fact about them, not a guess.

`server_default="1"` on add, and **kept**, for `3b7c1d5a92e4`'s reason:
dropping it would cost a second table copy to remove a default the mapper
declares too.

`batch_alter_table` because the target is SQLite, which has no full
`ALTER TABLE`; alembic rebuilds and copies.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "68c8b2a80ca9"
down_revision: str | None = "3b7c1d5a92e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "llm_parallel_calls",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.drop_column("llm_parallel_calls")
