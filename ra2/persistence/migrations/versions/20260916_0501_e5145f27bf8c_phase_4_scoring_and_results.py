"""phase 4: scoring and results

Revision ID: e5145f27bf8c
Revises: 9e90e50a151f
Create Date: 2026-09-16 05:01:16.276305+00:00

The last two tables `mvp-spec.md` §5 names — `score` and `mismatch`
(sw-design.md §16) — plus `evaluation.min_cell_count` (SD19). Nothing in §5 is
unbuilt after this.

**Written in full at Wave 0, not as a stub**, for the reason P3-D11 records:
this revision also **alters `evaluation`**, so every phase-1/2/3 test that
seeds an evaluation row fails with `no such column` the moment `models.py`
declares `min_cell_count` and the migration does not create it.
plan-phase-4.md §5.2's "every earlier test still green — this wave adds
surface, it does not change behaviour" is the stricter criterion and wins.
**S4 remains phase 4's one migration author** for anything Wave 1 adds on top
(CLAUDE.md).

Three details carry invariants rather than tidiness:

- **`score.language` is `NOT NULL`**, against mvp-spec.md §5's `language|NULL`
  (SD16). It is part of the composite primary key, and SQL treats two NULLs as
  distinct in a unique constraint — a nullable column here would permit exactly
  the duplicate rows the key looks like it prevents, and "rewrite this
  feature's rows" would orphan the old ones on every re-score. The
  all-languages row carries `domain.scoring.ALL_LANGUAGES` (`'*'`).
- **`UNIQUE (run_id, record_id, feature_id)` on `mismatch`** is what makes the
  tag-preserving upsert expressible (§16.6, SD21). `mismatch` is the one
  mutable row in this pipeline; a re-score rewrites its derived columns and
  must leave `analyst_tag`, `tagged_at` and `note` alone.
- **`min_cell_count` is added with a server default and then has it dropped.**
  The column is `NOT NULL` and `evaluation` may already hold rows, so the add
  needs a value for them; the ORM declares no server default, so leaving one
  behind would fail `alembic check`, which runs with `compare_server_default`
  on. Two batch passes, and the schema matches `models.py` exactly afterwards.

`ix_score_run_id` and `ix_mismatch_run_id_feature_id` are not decoration:
"is this run scored" is `COUNT(DISTINCT feature_id)` over `score` and there is
deliberately no status column to read instead (§16.1, F5).

Generated with `alembic revision --autogenerate` against a scratch copy of this
chain, then hand-adjusted where autogenerate says to: the docstring, the
server-default dance above, and `tagged_at`'s type.

**`tagged_at` is `sa.DateTime(timezone=True)`, not `models.UtcDateTime`**,
although the ORM declares the latter. Autogenerate rendered the app class and
imported `ra2.persistence.models` to reach it; that is wrong twice over. It
deadlocks in practice — `env.py` is itself mid-import of that module when a
migration runs inside the test suite, so the attribute is not yet bound — and
it is wrong in principle: **an applied migration must not depend on app code**,
because a later rename of a class would break a revision that has already run
everywhere (sw-design.md §12.3, "never edit an applied migration"). The
decorator's `impl` *is* `DateTime(timezone=True)` and the stored bytes are
identical, so the plain type is the same schema — which is why `alembic check`
sees no drift and why every earlier revision in this chain spells it this way.

Never edit an applied migration — add a new one (sw-design.md §12.3).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5145f27bf8c"
down_revision: str | None = "9e90e50a151f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mismatch",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("feature_id", sa.String(length=36), nullable=False),
        sa.Column("record_value", sa.Text(), nullable=True),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.Column("analyst_tag", sa.String(length=32), nullable=True),
        sa.Column("tagged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["feature.id"],
            name=op.f("fk_mismatch_feature_id_feature"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["record.id"],
            name=op.f("fk_mismatch_record_id_record"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["run.id"], name=op.f("fk_mismatch_run_id_run"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mismatch")),
        sa.UniqueConstraint(
            "run_id",
            "record_id",
            "feature_id",
            name=op.f("uq_mismatch_run_id_record_id_feature_id"),
        ),
    )
    with op.batch_alter_table("mismatch", schema=None) as batch_op:
        batch_op.create_index(
            "ix_mismatch_run_id_feature_id", ["run_id", "feature_id"], unique=False
        )

    op.create_table(
        "score",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("feature_id", sa.String(length=36), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("ci_low", sa.Float(), nullable=True),
        sa.Column("ci_high", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["feature.id"],
            name=op.f("fk_score_feature_id_feature"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["run.id"], name=op.f("fk_score_run_id_run"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "feature_id", "language", "metric", name=op.f("pk_score")
        ),
    )
    with op.batch_alter_table("score", schema=None) as batch_op:
        batch_op.create_index("ix_score_run_id", ["run_id"], unique=False)

    # `NOT NULL` on a table that may already hold rows: the default gives the
    # existing ones a value, and the second pass removes it so the schema
    # matches `models.py`, which declares none (`alembic check` runs with
    # `compare_server_default=True`).
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("min_cell_count", sa.Integer(), nullable=False, server_default="20")
        )
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.alter_column("min_cell_count", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.drop_column("min_cell_count")

    with op.batch_alter_table("score", schema=None) as batch_op:
        batch_op.drop_index("ix_score_run_id")

    op.drop_table("score")
    with op.batch_alter_table("mismatch", schema=None) as batch_op:
        batch_op.drop_index("ix_mismatch_run_id_feature_id")

    op.drop_table("mismatch")
