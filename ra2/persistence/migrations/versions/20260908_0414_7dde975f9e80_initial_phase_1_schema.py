"""initial phase-1 schema

Revision ID: 7dde975f9e80
Revises:
Create Date: 2026-09-08 04:14:02.587658+00:00

The **single** initial migration for the whole phase-1 schema
(`ra2/persistence/models.py`, frozen at M0). Generated with
`alembic revision --autogenerate` against the frozen `env.py`, then
hand-checked against `models.py`'s `NAMING_CONVENTION` and
`type_annotation_map` — every constraint name below matches what
`alembic check` would derive from the ORM metadata, so autogenerate and the
models never drift.

Table order follows dependency order (parent before child), matching the
sections of `models.py`: delivery staging (SD1) -> corpus (mvp-spec.md §5,
SD4) -> the EAV cell tables (D10) -> the materialised census (SD2, §4.2) ->
evaluation (M0-D1, phase-1 exists only to exercise the corpus delete guard).

Never edit an applied migration — add a new one (sw-design.md §12.3).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7dde975f9e80"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- delivery staging (SD1) — the only mutable tables --------------------
    op.create_table(
        "delivery",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("analysed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery")),
    )

    # --- corpus (mvp-spec.md §5, SD4) — immutable once frozen -----------------
    op.create_table(
        "corpus",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_file_manifest_json", sa.Text(), nullable=False),
        sa.Column("import_report_json", sa.Text(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("is_dev_sized", sa.Boolean(), nullable=False),
        sa.Column("cp1252_canary_count", sa.Integer(), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=True),
        sa.Column("source_file_ids_json", sa.Text(), nullable=True),
        sa.Column("language_counts_json", sa.Text(), nullable=True),
        sa.CheckConstraint("record_count >= 0", name=op.f("ck_corpus_record_count_non_negative")),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["delivery.id"],
            name=op.f("fk_corpus_delivery_id_delivery"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corpus")),
        sa.UniqueConstraint("name", "version", name="uq_corpus_name_version"),
    )

    op.create_table(
        "delivery_file",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=400), nullable=False),
        sa.Column("relative_path", sa.String(length=1000), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_kind", sa.String(length=16), nullable=False),
        sa.Column("set_key", sa.String(length=64), nullable=True),
        sa.Column("canton", sa.String(length=16), nullable=True),
        sa.Column("encoding", sa.String(length=32), nullable=True),
        sa.Column("delimiter", sa.String(length=4), nullable=True),
        sa.Column("quote_char", sa.String(length=4), nullable=True),
        sa.Column("encoding_detected", sa.String(length=32), nullable=True),
        sa.Column("dialect_detected", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("ok_count", sa.Integer(), nullable=False),
        sa.Column("recovered_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("header_ok", sa.Boolean(), nullable=True),
        sa.Column("findings_json", sa.Text(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("analysed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["delivery.id"],
            name=op.f("fk_delivery_file_delivery_id_delivery"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_file")),
        sa.UniqueConstraint("delivery_id", "relative_path", name="uq_delivery_file_path"),
    )
    op.create_index("ix_delivery_file_delivery_id", "delivery_file", ["delivery_id"])

    op.create_table(
        "record",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("corpus_id", sa.String(length=36), nullable=False),
        sa.Column("unfall_uid", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("language_confidence", sa.Float(), nullable=False),
        sa.Column("text_raw", sa.Text(), nullable=True),
        sa.Column("text_anonymised_flag", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["corpus_id"],
            ["corpus.id"],
            name=op.f("fk_record_corpus_id_corpus"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record")),
        sa.UniqueConstraint("corpus_id", "unfall_uid", name="uq_record_corpus_unfall_uid"),
    )
    op.create_index("ix_record_corpus_id", "record", ["corpus_id"])

    # --- EAV cell tables (D10) — 67 / 77 / 18 wide columns, in long form ------
    op.create_table(
        "unfall_row",
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("column_name", sa.String(length=100), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["record.id"],
            name=op.f("fk_unfall_row_record_id_record"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("record_id", "column_name", name=op.f("pk_unfall_row")),
    )
    op.create_index(
        "ix_unfall_row_record_id_column_name", "unfall_row", ["record_id", "column_name"]
    )

    op.create_table(
        "objekt_row",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("objekt_uid", sa.String(length=32), nullable=False),
        sa.Column("obj_nr", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["record.id"],
            name=op.f("fk_objekt_row_record_id_record"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_objekt_row")),
        sa.UniqueConstraint("record_id", "objekt_uid", name="uq_objekt_row_record_objekt_uid"),
    )
    op.create_index("ix_objekt_row_record_id", "objekt_row", ["record_id"])

    op.create_table(
        "objekt_cell",
        sa.Column("objekt_row_id", sa.String(length=36), nullable=False),
        sa.Column("column_name", sa.String(length=100), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["objekt_row_id"],
            ["objekt_row.id"],
            name=op.f("fk_objekt_cell_objekt_row_id_objekt_row"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("objekt_row_id", "column_name", name=op.f("pk_objekt_cell")),
    )
    op.create_index(
        "ix_objekt_cell_objekt_row_id_column_name",
        "objekt_cell",
        ["objekt_row_id", "column_name"],
    )

    op.create_table(
        "person_row",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("objekt_row_id", sa.String(length=36), nullable=False),
        sa.Column("person_uid", sa.String(length=32), nullable=False),
        sa.Column("pers_nr", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["objekt_row_id"],
            ["objekt_row.id"],
            name=op.f("fk_person_row_objekt_row_id_objekt_row"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_row")),
        sa.UniqueConstraint("objekt_row_id", "person_uid", name="uq_person_row_objekt_person_uid"),
    )
    op.create_index("ix_person_row_objekt_row_id", "person_row", ["objekt_row_id"])

    op.create_table(
        "person_cell",
        sa.Column("person_row_id", sa.String(length=36), nullable=False),
        sa.Column("column_name", sa.String(length=100), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_row_id"],
            ["person_row.id"],
            name=op.f("fk_person_cell_person_row_id_person_row"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("person_row_id", "column_name", name=op.f("pk_person_cell")),
    )
    op.create_index(
        "ix_person_cell_person_row_id_column_name",
        "person_cell",
        ["person_row_id", "column_name"],
    )

    # --- materialised census (SD2, §4.2) — computed once, at freeze -----------
    op.create_table(
        "census_column",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("corpus_id", sa.String(length=36), nullable=False),
        sa.Column("table_name", sa.String(length=32), nullable=False),
        sa.Column("column_name", sa.String(length=100), nullable=False),
        sa.Column("type_hint", sa.String(length=16), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("populated_count", sa.Integer(), nullable=False),
        sa.Column("populated_rate", sa.Float(), nullable=False),
        sa.Column("distinct_count", sa.Integer(), nullable=False),
        sa.Column("top_value_share", sa.Float(), nullable=False),
        sa.Column("long_tail", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "populated_rate >= 0.0 AND populated_rate <= 1.0",
            name=op.f("ck_census_column_populated_rate_is_a_rate"),
        ),
        sa.ForeignKeyConstraint(
            ["corpus_id"],
            ["corpus.id"],
            name=op.f("fk_census_column_corpus_id_corpus"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_census_column")),
        sa.UniqueConstraint(
            "corpus_id", "table_name", "column_name", name="uq_census_column_corpus_table_column"
        ),
    )
    op.create_index("ix_census_column_corpus_id", "census_column", ["corpus_id"])

    op.create_table(
        "census_value",
        sa.Column("census_column_id", sa.String(length=36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("share", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["census_column_id"],
            ["census_column.id"],
            name=op.f("fk_census_value_census_column_id_census_column"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("census_column_id", "rank", name=op.f("pk_census_value")),
    )

    op.create_table(
        "census_bucket",
        sa.Column("corpus_id", sa.String(length=36), nullable=False),
        sa.Column("bucket_label", sa.String(length=16), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["corpus_id"],
            ["corpus.id"],
            name=op.f("fk_census_bucket_corpus_id_corpus"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("corpus_id", "bucket_label", name=op.f("pk_census_bucket")),
    )

    # --- evaluation (M0-D1) — phase 2 table; seeded in phase 1 only to -------
    # --- exercise the corpus delete guard (sw-design.md §6.3, J3) ------------
    op.create_table(
        "evaluation",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("corpus_id", sa.String(length=36), nullable=False),
        sa.Column("feature_config_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_dev", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["corpus_id"],
            ["corpus.id"],
            name=op.f("fk_evaluation_corpus_id_corpus"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation")),
    )
    op.create_index("ix_evaluation_corpus_id", "evaluation", ["corpus_id"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_corpus_id", table_name="evaluation")
    op.drop_table("evaluation")

    op.drop_table("census_bucket")
    op.drop_table("census_value")
    op.drop_index("ix_census_column_corpus_id", table_name="census_column")
    op.drop_table("census_column")

    op.drop_index("ix_person_cell_person_row_id_column_name", table_name="person_cell")
    op.drop_table("person_cell")
    op.drop_index("ix_person_row_objekt_row_id", table_name="person_row")
    op.drop_table("person_row")
    op.drop_index("ix_objekt_cell_objekt_row_id_column_name", table_name="objekt_cell")
    op.drop_table("objekt_cell")
    op.drop_index("ix_objekt_row_record_id", table_name="objekt_row")
    op.drop_table("objekt_row")
    op.drop_index("ix_unfall_row_record_id_column_name", table_name="unfall_row")
    op.drop_table("unfall_row")

    op.drop_index("ix_record_corpus_id", table_name="record")
    op.drop_table("record")
    op.drop_index("ix_delivery_file_delivery_id", table_name="delivery_file")
    op.drop_table("delivery_file")
    op.drop_table("corpus")
    op.drop_table("delivery")
