"""phase 3: prompts and runs

Revision ID: 9e90e50a151f
Revises: 4995824acfe4
Create Date: 2026-09-13 00:00:00.000000+00:00

The six phase-3 tables `ra2/persistence/models.py` (M17, Wave 0) declares —
`prompt_template`, `evaluation_feature`, `run`, `extraction`,
`extraction_value`, `extraction_entity` (mvp-spec.md §5, sw-design.md §15) —
plus the seven setup columns `evaluation` gains (SD13) and the foreign key
from `evaluation.prompt_template_id`.

**Why this is not the empty stub plan-phase-3.md §5.1 asked for.** That
instruction was written from phase 2's shape, where Wave 0 added only *new*
tables: an empty revision left an honest gap that broke nothing, and D3 filled
it in. Phase 3 also **alters an existing table** — every `evaluation` insert
in the phase-1 and phase-2 suites fails the moment `models.py` declares the
new columns and the migration does not create them. §5.2 is explicit that
"every phase-1 and phase-2 test still green — this wave adds surface, it does
not change behaviour", and that criterion is the stricter one. So the
migration is written here, plan-phase-3.md §5.1/§6/§7 are corrected in the
same commit (CLAUDE.md: "where it is wrong, raise it and change *that file*
first"), and **H3 remains phase 3's one migration author** for everything
Wave 1 adds on top. Recorded as P3-D11 in CONTRACTS.md.

Two constraints carry invariants rather than tidiness:

- `UNIQUE (run_id, record_id)` on `extraction` **is the resume key**
  (sw-design.md §15.3). Resume is "the record ids in this run's scope with no
  `extraction` row", and the constraint is what makes a double write raise
  instead of quietly updating (Do-NOT #2).
- `run.prompt_template_id` is `ondelete="RESTRICT"` — that *is* "delete only
  when uncited" (§15.1). The database refuses to drop a version a run cites.

`ix_extraction_run_id` is not decoration either: progress is
`COUNT(extraction WHERE run_id = …)` and there is deliberately no counter
column to read instead (§15 F6).

Generated with `alembic revision --autogenerate` against a scratch copy of
this chain, then hand-checked against `models.py`'s `NAMING_CONVENTION` and
`type_annotation_map` — every constraint name below matches what
`alembic check` derives from the ORM metadata, so autogenerate and the models
never drift. The `evaluation` alter uses `batch_alter_table`, following the
idiom in `20260908_1740_a39c30e4559d_...` and
`20260912_0000_4995824acfe4_...`: SQLite cannot `ALTER COLUMN` or add a
foreign key in place, so batch mode rebuilds the table.

Never edit an applied migration — add a new one (sw-design.md §12.3).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9e90e50a151f"
down_revision: str | None = "4995824acfe4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_template",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_prompt_template_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_template")),
        sa.UniqueConstraint("version", name="uq_prompt_template_version"),
    )
    op.create_table(
        "evaluation_feature",
        sa.Column("evaluation_id", sa.String(length=36), nullable=False),
        sa.Column("feature_id", sa.String(length=36), nullable=False),
        sa.Column("enum_codelist_json", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["evaluation.id"],
            name=op.f("fk_evaluation_feature_evaluation_id_evaluation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["feature.id"],
            name=op.f("fk_evaluation_feature_feature_id_feature"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evaluation_id", "feature_id", name=op.f("pk_evaluation_feature")),
    )
    with op.batch_alter_table("evaluation_feature", schema=None) as batch_op:
        batch_op.create_index(
            "ix_evaluation_feature_evaluation_id", ["evaluation_id"], unique=False
        )

    op.create_table(
        "run",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_id", sa.String(length=36), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("model_digest", sa.String(length=64), nullable=False),
        sa.Column("prompt_template_version", sa.Integer(), nullable=False),
        sa.Column("prompt_template_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_template_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("host_platform", sa.String(length=200), nullable=False),
        sa.Column("gpu_name", sa.String(length=200), nullable=True),
        sa.Column("llm_endpoint", sa.String(length=400), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["evaluation.id"],
            name=op.f("fk_run_evaluation_id_evaluation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_template.id"],
            name=op.f("fk_run_prompt_template_id_prompt_template"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run")),
    )
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.create_index("ix_run_evaluation_id", ["evaluation_id"], unique=False)

    op.create_table(
        "extraction",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("raw_output_text", sa.Text(), nullable=False),
        sa.Column("parse_ok", sa.Boolean(), nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["record.id"],
            name=op.f("fk_extraction_record_id_record"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["run.id"], name=op.f("fk_extraction_run_id_run"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction")),
        sa.UniqueConstraint("run_id", "record_id", name="uq_extraction_run_record"),
    )
    with op.batch_alter_table("extraction", schema=None) as batch_op:
        batch_op.create_index("ix_extraction_run_id", ["run_id"], unique=False)

    op.create_table(
        "extraction_entity",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("extraction_id", sa.String(length=36), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("entity_ref", sa.String(length=32), nullable=False),
        sa.Column("attributes_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extraction.id"],
            name=op.f("fk_extraction_entity_extraction_id_extraction"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_entity")),
    )
    with op.batch_alter_table("extraction_entity", schema=None) as batch_op:
        batch_op.create_index("ix_extraction_entity_extraction_id", ["extraction_id"], unique=False)

    op.create_table(
        "extraction_value",
        sa.Column("extraction_id", sa.String(length=36), nullable=False),
        sa.Column("feature_id", sa.String(length=36), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=True),
        sa.Column("value_normalised", sa.Text(), nullable=True),
        sa.Column("present_flag", sa.Boolean(), nullable=False),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extraction.id"],
            name=op.f("fk_extraction_value_extraction_id_extraction"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["feature.id"],
            name=op.f("fk_extraction_value_feature_id_feature"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("extraction_id", "feature_id", name=op.f("pk_extraction_value")),
    )
    # The four NOT NULL columns carry a `server_default` **for the backfill
    # only**: an existing `evaluation` row has no value for them, and SQLite's
    # batch mode rebuilds the table with `INSERT ... SELECT`, which would hit
    # the NOT NULL constraint. The defaults match `models.py`'s Python-side
    # ones (the design's 0.0 / 42 / full / de). They are dropped in the second
    # batch below so `alembic check` sees no drift — `models.py` declares no
    # server default.
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.add_column(sa.Column("prompt_template_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("prompt_language", sa.String(length=16), nullable=False, server_default="de")
        )
        batch_op.add_column(
            sa.Column("temperature", sa.Float(), nullable=False, server_default="0.0")
        )
        batch_op.add_column(sa.Column("seed", sa.Integer(), nullable=False, server_default="42"))
        batch_op.add_column(
            sa.Column("size", sa.String(length=16), nullable=False, server_default="full")
        )
        batch_op.add_column(sa.Column("selected_models_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_evaluation_prompt_template_id_prompt_template"),
            "prompt_template",
            ["prompt_template_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.alter_column("prompt_language", server_default=None)
        batch_op.alter_column("temperature", server_default=None)
        batch_op.alter_column("seed", server_default=None)
        batch_op.alter_column("size", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("evaluation", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_evaluation_prompt_template_id_prompt_template"), type_="foreignkey"
        )
        batch_op.drop_column("launched_at")
        batch_op.drop_column("selected_models_json")
        batch_op.drop_column("size")
        batch_op.drop_column("seed")
        batch_op.drop_column("temperature")
        batch_op.drop_column("prompt_language")
        batch_op.drop_column("prompt_template_id")

    op.drop_table("extraction_value")
    with op.batch_alter_table("extraction_entity", schema=None) as batch_op:
        batch_op.drop_index("ix_extraction_entity_extraction_id")

    op.drop_table("extraction_entity")
    with op.batch_alter_table("extraction", schema=None) as batch_op:
        batch_op.drop_index("ix_extraction_run_id")

    op.drop_table("extraction")
    with op.batch_alter_table("run", schema=None) as batch_op:
        batch_op.drop_index("ix_run_evaluation_id")

    op.drop_table("run")
    with op.batch_alter_table("evaluation_feature", schema=None) as batch_op:
        batch_op.drop_index("ix_evaluation_feature_evaluation_id")

    op.drop_table("evaluation_feature")
    op.drop_table("prompt_template")
