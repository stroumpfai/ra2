"""drop census_column populated_rate upper bound

Revision ID: a39c30e4559d
Revises: 7dde975f9e80
Create Date: 2026-09-08 17:40:57.878230+00:00

Never edit an applied migration — add a new one (sw-design.md §12.3).

`compute_census` (ra2/domain/census.py) uses the corpus *record* count as the
denominator for every table so rates are comparable across tables
(sw-design.md §7), but `objekt`/`person` are one-to-many with `record`: a
multi-vehicle accident's `objekt` columns legitimately populate more cells
than there are records, so `populated_rate` can exceed 1.0. Found at Wave 2
integration (B2): the `<= 1.0` upper bound in the initial schema made
`corpus_service.freeze()` crash on any real delivery with more than one
object per accident. Autogenerate did not detect this — SQLite's CHECK
constraints are not reliably reflected — so this migration is hand-written.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a39c30e4559d"
down_revision: str | None = "7dde975f9e80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The bare logical name, matching `models.py`'s `CheckConstraint(name=...)`.
#: Batch mode applies the naming convention itself (-> `ck_census_column_...`);
#: passing the already-expanded name here double-prefixes it.
_CONSTRAINT_NAME = "populated_rate_is_a_rate"


def upgrade() -> None:
    with op.batch_alter_table("census_column", recreate="always") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(_CONSTRAINT_NAME, "populated_rate >= 0.0")


def downgrade() -> None:
    with op.batch_alter_table("census_column", recreate="always") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(
            _CONSTRAINT_NAME, "populated_rate >= 0.0 AND populated_rate <= 1.0"
        )
