"""pin the reasoning effort on the run

Revision ID: 090e7fdc12c5
Revises: e5145f27bf8c
Create Date: 2026-09-20 07:29:48.703907+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`run.llm_reasoning_effort` — `RA2_LLM_REASONING_EFFORT` as the run asked it,
beside the model digest, the temperature and the seed, because it decides the
answer as much as they do. Measured on the reporting host, one record with two
features and one sentence of narrative against `qwen3.5:latest` (9.7 B Q4_K_M,
CPU-bound), through the adapter's own call shape: **190 s** at the model's own
default, **6 s** at `none`. Both answered correctly. The first never finished
a 12-record run inside `RA2_LLM_TIMEOUT_S`.

Whether the thinking one is *better* is precisely the question RA2 exists to
answer, so the value is a setting rather than a constant — and pinned here
rather than left in the environment, because two runs that asked different
questions must not look identical in provenance afterwards (mvp-spec.md
§19.8).

**Nullable, with no backfill.** Rows written before this column existed did
not record an effort, and there is no honest value to invent for them: the
adapter sent no `reasoning_effort` at all, so the model's own default applied
and nothing here knows what that was. `NULL` reads as "this run did not record
it", which is `run.gpu_name`'s convention for the same situation (§15.6).

**Why this phase gets a revision at all.** `plan-phase-5.md` C7 expected none
and CLAUDE.md names one author anyway, "because the rule that matters is that
there is exactly one". This is that one: a single head, additive, no data
rewritten. It arrives from a reproduced defect rather than from a wave
(`contracts/amendments/fix-evaluation-timeout-and-progress.md`, item 16).

`batch_alter_table` because the target is SQLite, which has no full
`ALTER TABLE`; alembic rebuilds and copies. Additive and nullable, so the
rebuild carries every existing row through unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "090e7fdc12c5"
down_revision: str | None = "e5145f27bf8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("llm_reasoning_effort", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.drop_column("llm_reasoning_effort")
