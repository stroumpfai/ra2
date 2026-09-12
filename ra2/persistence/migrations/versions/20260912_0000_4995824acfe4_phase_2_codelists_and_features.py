"""phase 2: codelists and features

Revision ID: 4995824acfe4
Revises: a39c30e4559d
Create Date: 2026-09-12 00:00:00.000000+00:00

Adds the six phase-2 tables `ra2/persistence/models.py` (M9, Wave 0) already
declares — `code_table_import`, `code_attribute`, `code_value`,
`column_mapping`, `feature_config`, `feature` (sw-design.md §14,
mvp-spec.md §5/§7/§8) — and turns `evaluation.feature_config_id` from a
plain, FK-less string (M0-D1) into a real, non-nullable foreign key onto
`feature_config.id` with `ondelete="RESTRICT"` (mvp-spec.md §9: a frozen
config an evaluation cites cannot be deleted out from under it).

Table order follows `models.py`'s own section order: Codelists
(`code_table_import` -> `code_attribute` -> `code_value` ->
`column_mapping`) before Feature configuration (`feature_config` ->
`feature`), then the `evaluation` alter last, since it references
`feature_config`.

Generated with `alembic revision --autogenerate` against a scratch copy of
this chain (env.py + the two phase-1 revisions, no stub), then hand-checked
against `models.py`'s `NAMING_CONVENTION` and `type_annotation_map` — every
constraint name below matches what `alembic check` would derive from the ORM
metadata, so autogenerate and the models never drift. The `evaluation` alter
uses `batch_alter_table`, following the idiom in
`20260908_1740_a39c30e4559d_drop_census_column_populated_rate_upper_.py`:
SQLite cannot `ALTER COLUMN` or add a foreign key in place, so batch mode
rebuilds the table.

Never edit an applied migration — add a new one (sw-design.md §12.3).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4995824acfe4"
down_revision: str | None = "a39c30e4559d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Codelists (sw-design.md §14, mvp-spec.md §5/§7) ---------------------
    op.create_table(
        "code_table_import",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_file", sa.String(length=400), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_table_import")),
    )

    op.create_table(
        "code_attribute",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code_table_import_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("chapter", sa.String(length=32), nullable=True),
        sa.Column("name_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["code_table_import_id"],
            ["code_table_import.id"],
            name=op.f("fk_code_attribute_code_table_import_id_code_table_import"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_attribute")),
        sa.UniqueConstraint("code_table_import_id", "key", name="uq_code_attribute_import_key"),
    )
    op.create_index(
        "ix_code_attribute_code_table_import_id", "code_attribute", ["code_table_import_id"]
    )

    op.create_table(
        "code_value",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code_attribute_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["code_attribute_id"],
            ["code_attribute.id"],
            name=op.f("fk_code_value_code_attribute_id_code_attribute"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_value")),
        sa.UniqueConstraint("code_attribute_id", "code", name="uq_code_value_attribute_code"),
    )
    op.create_index("ix_code_value_code_attribute_id", "code_value", ["code_attribute_id"])

    op.create_table(
        "column_mapping",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("corpus_id", sa.String(length=36), nullable=False),
        sa.Column("source_column", sa.String(length=100), nullable=False),
        sa.Column("code_attribute_id", sa.String(length=36), nullable=False),
        sa.Column("mapped_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["code_attribute_id"],
            ["code_attribute.id"],
            name=op.f("fk_column_mapping_code_attribute_id_code_attribute"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["corpus_id"],
            ["corpus.id"],
            name=op.f("fk_column_mapping_corpus_id_corpus"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_column_mapping")),
        sa.UniqueConstraint("corpus_id", "source_column", name="uq_column_mapping_corpus_column"),
    )
    op.create_index("ix_column_mapping_corpus_id", "column_mapping", ["corpus_id"])

    # --- Feature configuration (mvp-spec.md §8) -------------------------------
    op.create_table(
        "feature_config",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feature_config")),
        sa.UniqueConstraint("name", "version", name="uq_feature_config_name_version"),
    )

    op.create_table(
        "feature",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("feature_config_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("grain", sa.String(length=16), nullable=False),
        sa.Column("source_column", sa.String(length=100), nullable=True),
        sa.Column("derivation_json", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("matching_rule", sa.Text(), nullable=False),
        sa.Column("enum_codelist_json", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["feature_config_id"],
            ["feature_config.id"],
            name=op.f("fk_feature_feature_config_id_feature_config"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feature")),
        sa.UniqueConstraint("feature_config_id", "key", name="uq_feature_config_key"),
    )
    op.create_index("ix_feature_feature_config_id", "feature", ["feature_config_id"])

    # --- evaluation (M0-D1 -> a real FK) ---------------------------------------
    # SQLite cannot ALTER COLUMN or add a foreign key in place; batch mode
    # rebuilds the table, same idiom as a39c30e4559d.
    with op.batch_alter_table("evaluation", recreate="always") as batch_op:
        batch_op.alter_column(
            "feature_config_id", existing_type=sa.String(length=36), nullable=False
        )
        batch_op.create_foreign_key(
            "fk_evaluation_feature_config_id_feature_config",
            "feature_config",
            ["feature_config_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("evaluation", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "fk_evaluation_feature_config_id_feature_config", type_="foreignkey"
        )
        batch_op.alter_column(
            "feature_config_id", existing_type=sa.String(length=36), nullable=True
        )

    op.drop_index("ix_feature_feature_config_id", table_name="feature")
    op.drop_table("feature")
    op.drop_table("feature_config")

    op.drop_index("ix_column_mapping_corpus_id", table_name="column_mapping")
    op.drop_table("column_mapping")
    op.drop_index("ix_code_value_code_attribute_id", table_name="code_value")
    op.drop_table("code_value")
    op.drop_index("ix_code_attribute_code_table_import_id", table_name="code_attribute")
    op.drop_table("code_attribute")
    op.drop_table("code_table_import")
