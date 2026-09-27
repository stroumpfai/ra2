"""store the settings an analyst changes

Revision ID: ccbae1b96d1b
Revises: 9874691cc8eb
Create Date: 2026-09-27 15:10:04.673729+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`app_setting` — the two settings the Models card's settings dialog draws, the
LLM endpoint and its timeout, stored when an analyst saves them
(sw-design.md SD43). Until now the dialog saved nothing: it told the analyst to
set two environment variables and restart, which made a developer the only
person who could change the endpoint (`docs/risk-assesment.md` E3).

**A new table, append-only, referenced by nothing**; no existing row is
touched. A save adds a row and the newest per key wins — `model_qualification`'s
shape — so nothing ever updates one, and the history says when the endpoint
changed. The environment variables stay the seed: a database with no rows here
behaves exactly as before this revision.

`value_json` rather than a typed column per key, because the two keys hold a
URL and an integer and a third would otherwise cost a migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ccbae1b96d1b"
down_revision: str | None = "9874691cc8eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_setting")),
    )
    with op.batch_alter_table("app_setting", schema=None) as batch_op:
        batch_op.create_index("ix_app_setting_key_changed_at", ["key", "changed_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("app_setting", schema=None) as batch_op:
        batch_op.drop_index("ix_app_setting_key_changed_at")

    op.drop_table("app_setting")
