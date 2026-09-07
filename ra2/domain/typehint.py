# STUB — bodies owned by A2 (feat/m1-census). Not frozen.
"""Column type inference (sw-design.md §7).

The `Ausw`/`Feld` suffix rule runs **first**; value-shape inspection only
decides what the suffix leaves open. An `Ausw` column is `enum` even when every
value looks like an integer — there is a test that says so.
"""

from collections.abc import Iterable

from ra2.domain.census import TypeHint

__all__ = ["infer_type_hint"]


def infer_type_hint(column_name: str, values: Iterable[str]) -> TypeHint:
    """Infer a column's type from its name suffix, then its values.

    1. `*Ausw` -> `ENUM`, unconditionally.
    2. Otherwise, over the non-empty values: all `YYYYMMDD` in a plausible
       range -> `DATE`; all `HH:MM` -> `TIME`; all integral -> `INTEGER`;
       all decimal-parseable -> `DECIMAL`; else `TEXT`.
    3. A column with no populated values -> `TEXT`.
    """
    raise NotImplementedError
