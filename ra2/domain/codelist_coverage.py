# FROZEN (types and signature) — see CONTRACTS.md
"""Coverage derivation — missing / partial / ok (mvp-spec.md §7, sw-design.md §14.2).

Split from `codes.py` on purpose (sw-design.md §14.3): this is a pure
computation over plain values, while `codes.py` holds the imported shape
itself. Its only caller, `codelist_service.coverage()`, runs the `GROUP BY
value_raw` query over the corpus's EAV cells (sw-design.md §14.2 — a
deliberate, narrow exception to "no view queries EAV directly") and hands
this function the plain result; this module never sees a session.

**M9 freezes the types and the signature. D1 writes `compute_coverage`'s body.**
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ra2.domain.codes import CodeAttribute, CodeValue

__all__ = ["CodeUsage", "ColumnCoverage", "CoverageStatus", "compute_coverage"]


class CoverageStatus(StrEnum):
    """sw-design.md §14.2's three states, per mapped column per language."""

    #: No `column_mapping` row, or the mapped attribute has zero `CodeValue`s.
    MISSING = "missing"
    #: At least one code used by the corpus has no label in the language.
    PARTIAL = "partial"
    #: Every code appearing in the corpus has a label in the language.
    OK = "ok"


@dataclass(frozen=True, slots=True)
class CodeUsage:
    """One code appearing in the corpus, with its label and usage.

    `in_codelist=False` is the `Finding`-grade case mvp-spec.md §7 names: the
    code has **no row at all** in the mapped attribute, in any language —
    distinct from merely lacking a label in the configured language.
    """

    code: str
    count: int
    #: `count / populated_count` of the column, in [0, 1].
    share: float
    #: The label in the requested language, or `None`.
    label: str | None
    in_codelist: bool


@dataclass(frozen=True, slots=True)
class ColumnCoverage:
    """One mapped column's coverage, for one prompt language."""

    status: CoverageStatus
    language: str
    #: Usage-ordered (descending) — the codes table's row order (README).
    codes: tuple[CodeUsage, ...]
    #: Of the codes appearing in the corpus, how many carry a label in `language`.
    labelled_count: int
    #: Distinct codes appearing in the corpus.
    total_count: int
    #: `labelled_count / total_count`, or `0.0` when `total_count` is `0`.
    coverage_pct: float


def compute_coverage(
    cells: Sequence[tuple[str, int]],
    mapping: CodeAttribute | None,
    code_values: Sequence[CodeValue],
    language: str,
) -> ColumnCoverage:
    """Pure: `cells` is already the caller's `GROUP BY value_raw` result.

    :param cells: `(value_raw, count)` per distinct value appearing in the
        corpus for this column.
    :param mapping: the mapped attribute, or `None` for no mapping at all —
        always `MISSING`.
    :param code_values: the mapped attribute's codes. Empty means `MISSING`
        even when `mapping` is not `None` (sw-design.md §14.2).
    :param language: the configured prompt language (`de` / `fr` / `it`).
    """
    raise NotImplementedError
