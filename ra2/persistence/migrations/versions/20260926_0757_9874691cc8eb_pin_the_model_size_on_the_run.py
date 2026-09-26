"""pin the model size on the run

Revision ID: 9874691cc8eb
Revises: 7d084d5a7dc6
Create Date: 2026-09-26 07:57:26.523186+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`run.model_size_bytes` — the catalogue's `size_bytes` for this run's tag at
launch, the number the Models card showed beside the tick (sw-design.md SD41).
The ranking reports it as VRAM, in its own column and in the Model column's
`digest · size` sub-line, from one field, which is what makes the design's
"must agree with the model sub-line" hold by construction.

**NULLABLE, and not backfilled**, where `68c8b2a80ca9`'s `llm_parallel_calls`
is NOT NULL backfilled `1`. That backfill was a *fact*: no code before it could
put two records of one run in flight, so every existing row executed at 1.
There is no equivalent fact here — a run launched before this column simply did
not record its model's size, and any value chosen for it would be a number
nobody measured. The ranking renders the absence as an em dash; `0` is the
defect this column repairs.

`batch_alter_table` because the target is SQLite, which has no full
`ALTER TABLE`; alembic rebuilds and copies.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9874691cc8eb"
down_revision: str | None = "7d084d5a7dc6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("model_size_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.drop_column("model_size_bytes")
