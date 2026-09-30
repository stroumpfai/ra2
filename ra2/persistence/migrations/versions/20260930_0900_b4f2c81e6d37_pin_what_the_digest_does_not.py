"""pin what the digest does not

Revision ID: b4f2c81e6d37
Revises: 5e1d7a3c9b20
Create Date: 2026-09-30 09:00:00.000000+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

Three `run` columns, for what the model digest does not pin (sw-design.md
SD48, risks D1 and D3):

- `ollama_version`: the runtime the run launched against;
- `server_parameters_json`: the model's server-side decoding options
  (its Modelfile `PARAMETER`s) at launch;
- `context_length`: the context window the model was loaded with, read after
  the run's first record. The adapter sends none, so this is what the server
  applied, and it is what an extraction's `prompt_tokens` is compared with.

**All three NULLABLE, no backfill**, for `9874691cc8eb`'s reason: a run
launched before this revision recorded none of them, and any value written for
it would be a number nobody measured. `None` renders as *not recorded*, and an
extraction of such a run is never flagged as at the limit.

`batch_alter_table` because the target is SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4f2c81e6d37"
down_revision: str | None = "5e1d7a3c9b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ollama_version", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("server_parameters_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("context_length", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.drop_column("context_length")
        batch_op.drop_column("server_parameters_json")
        batch_op.drop_column("ollama_version")
