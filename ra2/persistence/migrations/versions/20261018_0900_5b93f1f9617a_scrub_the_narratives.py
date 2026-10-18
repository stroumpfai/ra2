"""scrub the narratives

Revision ID: 5b93f1f9617a
Revises: 3ce2190bd859
Create Date: 2026-10-18 09:00:00.000000+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

Narrative scrubbing (sw-design.md §19, `SD62`–`SD66`):

- `scrub_list`: one imported rule file or name list, stored whole, reused by
  `(kind, sha256)`;
- `scrub_ruleset`: one immutable version of the analyst's rule set, up to four
  lists, the highest version active;
- three nullable columns on `corpus`: the rule set it was scrubbed with, the
  fingerprint of everything that ran, and the mandatory rules as applied.

**No backfill, and no existing row touched.** A corpus that exists before this
revision was frozen verbatim, and `scrub_fingerprint IS NULL` is exactly how
it says so (the `NOT SCRUBBED` chip). Scrubbing it now would be an
`UPDATE record`, which Do-NOT #2 forbids; a scrubbed copy is a new freeze.

**`corpus` is altered in place, never rebuilt, in both directions.** Batch
mode would copy the table, drop the original and rename the copy, and
migrations run with `foreign_keys=ON` (`env.py` uses `session.create_engine`)
inside a transaction, where `PRAGMA foreign_keys=OFF` is a no-op. So the
`DROP TABLE corpus` would cascade through `record` and every table below it.
Native `ADD COLUMN` and `DROP COLUMN` never drop the table. That is also why
**`corpus.scrub_ruleset_id` is not a foreign key**: SQLite will not drop a
column that carries one without a rebuild. A rule set has no delete path, so
the reference cannot dangle. `tests/backend/persistence/test_migrations.py`
asserts that records survive both directions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b93f1f9617a"
down_revision: str | None = "3ce2190bd859"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrub_list",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=400), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("import_report_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('regex', 'firstname', 'lastname', 'whitelist')",
            name=op.f("ck_scrub_list_kind_known"),
        ),
        sa.CheckConstraint("entry_count >= 0", name=op.f("ck_scrub_list_entry_count_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scrub_list")),
        sa.UniqueConstraint("kind", "sha256", name="uq_scrub_list_kind_sha256"),
    )
    op.create_table(
        "scrub_ruleset",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("regex_list_id", sa.String(length=36), nullable=True),
        sa.Column("firstname_list_id", sa.String(length=36), nullable=True),
        sa.Column("lastname_list_id", sa.String(length=36), nullable=True),
        sa.Column("whitelist_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint("version >= 1", name=op.f("ck_scrub_ruleset_version_positive")),
        sa.ForeignKeyConstraint(
            ["regex_list_id"],
            ["scrub_list.id"],
            name=op.f("fk_scrub_ruleset_regex_list_id_scrub_list"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firstname_list_id"],
            ["scrub_list.id"],
            name=op.f("fk_scrub_ruleset_firstname_list_id_scrub_list"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lastname_list_id"],
            ["scrub_list.id"],
            name=op.f("fk_scrub_ruleset_lastname_list_id_scrub_list"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["whitelist_id"],
            ["scrub_list.id"],
            name=op.f("fk_scrub_ruleset_whitelist_id_scrub_list"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scrub_ruleset")),
        sa.UniqueConstraint("version", name="uq_scrub_ruleset_version"),
    )
    # Not `batch_alter_table`: see the docstring. Plain `ADD COLUMN`, in place.
    op.add_column("corpus", sa.Column("scrub_ruleset_id", sa.String(length=36), nullable=True))
    op.add_column("corpus", sa.Column("scrub_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("corpus", sa.Column("scrub_mandatory_json", sa.Text(), nullable=True))


def downgrade() -> None:
    # Native `DROP COLUMN` (SQLite 3.35+), never a batch rebuild of `corpus`.
    op.execute("ALTER TABLE corpus DROP COLUMN scrub_mandatory_json")
    op.execute("ALTER TABLE corpus DROP COLUMN scrub_fingerprint")
    op.execute("ALTER TABLE corpus DROP COLUMN scrub_ruleset_id")
    op.drop_table("scrub_ruleset")
    op.drop_table("scrub_list")
