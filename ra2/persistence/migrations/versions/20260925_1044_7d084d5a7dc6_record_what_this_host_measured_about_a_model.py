"""record what this host measured about a model

Revision ID: 7d084d5a7dc6
Revises: 68c8b2a80ca9
Create Date: 2026-09-25 10:44:12.900463+00:00

`model_qualification` (sw-design.md SD40, `plan-model-choice.md`): one row
per `just qualify-model` run, this host's measurement of one model
(tag, digest) over the synthetic seed. **Append-only**, and the newest per
(tag, digest) wins. It carries numbers only, and no other table references
it, so this revision touches nothing that exists.

Generated with `alembic revision --autogenerate` against a scratch database,
then hand-adjusted as `e5145f27bf8c` explains: `measured_at` is spelled
`sa.DateTime(timezone=True)`, not `models.UtcDateTime`, because an applied
migration must not depend on app code. The decorator's `impl` is that type,
so `alembic check` sees no drift.

The only revision of `plan-model-choice.md`, written by its implementer. No
parallel heads.

Never edit an applied migration — add a new one (sw-design.md §12.3).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d084d5a7dc6"
down_revision: str | None = "68c8b2a80ca9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_qualification",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("model_tag", sa.String(length=200), nullable=False),
        sa.Column("model_digest", sa.String(length=64), nullable=False),
        sa.Column("ollama_version", sa.String(length=64), nullable=True),
        sa.Column("gpu_name", sa.String(length=200), nullable=True),
        sa.Column("ra2_version", sa.String(length=64), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seed_records", sa.Integer(), nullable=False),
        sa.Column("quality_json", sa.Text(), nullable=False),
        sa.Column("gate_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "seed_records > 0", name=op.f("ck_model_qualification_seed_records_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_qualification")),
    )
    with op.batch_alter_table("model_qualification", schema=None) as batch_op:
        batch_op.create_index(
            "ix_model_qualification_tag_digest",
            ["model_tag", "model_digest", "measured_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("model_qualification", schema=None) as batch_op:
        batch_op.drop_index("ix_model_qualification_tag_digest")

    op.drop_table("model_qualification")
