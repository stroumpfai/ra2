"""Mapping suggestions — automap's pure half (plan-codelists-usability.md §4.1).

The Codelists view's "Automap…" proposes a code attribute for a census column,
and the analyst confirms (mvp-spec.md §7: the mapping is "analyst-set"). This
module decides *what* to propose, from plain values only; it never sees a
session, and `codelist_service.suggest_mappings` is its one caller.

Two sources, in order of trust:

1. **Copied** — the attribute key another corpus maps the same column name
   to. Deterministic: it is a decision an analyst already made.
2. **Overlap** — the attribute whose codes contain every value the column
   holds, *strictly* ahead of every other attribute that also does. Codes are
   mostly small integers, so `{1, 2, 3}` sits inside half a code table; this
   source only ever proposes, and the view leaves it unchecked. A column with
   fewer than `MIN_OVERLAP_DISTINCT` distinct values gets none: one value is
   inside *every* attribute that has it, so "the tightest fit" is then just
   the smallest attribute, whatever the column means.

Codes match **exactly**: `"04"` is not `"4"`. Coercing a value to the nearest
code is what mvp-spec.md §7 forbids, and a column whose leading zeros were lost
shows up here as no overlap, which is the truth about it.

Name matching is deliberately absent: the real code table's keys are English
(`weather`) and the columns German (`WitterungAusw`), so a matcher right on
the synthetic seed would be wrong on the real file (plan §1).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "MIN_OVERLAP_DISTINCT",
    "MappingSuggestion",
    "Overlap",
    "SuggestionSource",
    "rank_attributes",
    "suggest_mappings",
]

#: Below this many distinct values, overlap is no evidence (module docstring).
#: Copied suggestions have no such floor: they rest on a decision, not on data.
MIN_OVERLAP_DISTINCT = 2


class SuggestionSource(StrEnum):
    """Where a suggestion came from. Stable identifiers; the words for them
    are a rendering table in `ui/`."""

    #: The source corpus maps this column name to this attribute key.
    COPIED = "copied"
    #: Ranked by code-value overlap alone.
    OVERLAP = "overlap"


@dataclass(frozen=True, slots=True)
class Overlap:
    """How well one attribute's codes cover one column's values."""

    attribute_key: str
    #: Distinct column values that are codes of the attribute.
    contained: int
    #: Distinct column values.
    distinct: int
    #: The share of the column's *records* whose value is a code, in [0, 1] —
    #: a stray value on one record weighs little.
    records_contained: float
    #: |values ∩ codes| / |values ∪ codes|, in [0, 1] — prefers the
    #: attribute that is *just* big enough over one that contains everything.
    jaccard: float

    @property
    def covers(self) -> bool:
        """Every distinct value the column holds is a code."""
        return self.contained == self.distinct


@dataclass(frozen=True, slots=True)
class MappingSuggestion:
    column_name: str
    attribute_key: str
    source: SuggestionSource
    #: Attached to a copied suggestion too, so a bad copy is visible.
    overlap: Overlap


def suggest_mappings(
    columns: Mapping[str, Sequence[tuple[str, int]]],
    attributes: Mapping[str, frozenset[str]],
    copied: Mapping[str, str],
) -> tuple[MappingSuggestion, ...]:
    """At most one suggestion per column, in `columns`' order.

    :param columns: column name → its `GROUP BY value_raw` cells, empty
        values already excluded (`CodelistRepository.coverage_counts`).
    :param attributes: attribute key → its codes, from the current import.
    :param copied: column name → the attribute key the source corpus maps it
        to. A key `attributes` does not have yields **no** suggestion for that
        column — never a silent fall-back to overlap; the caller reports it.
    """
    suggestions: list[MappingSuggestion] = []
    for column_name, cells in columns.items():
        if not cells:
            # All empty: nothing to overlap, and nothing a prompt will ask.
            continue
        if column_name in copied:
            key = copied[column_name]
            if key in attributes:
                suggestions.append(
                    MappingSuggestion(
                        column_name=column_name,
                        attribute_key=key,
                        source=SuggestionSource.COPIED,
                        overlap=_overlap(cells, key, attributes[key]),
                    )
                )
            continue
        if len(cells) < MIN_OVERLAP_DISTINCT:
            continue
        best = _clear_winner(rank_attributes(cells, attributes))
        if best is not None:
            suggestions.append(
                MappingSuggestion(
                    column_name=column_name,
                    attribute_key=best.attribute_key,
                    source=SuggestionSource.OVERLAP,
                    overlap=best,
                )
            )
    return tuple(suggestions)


def rank_attributes(
    cells: Sequence[tuple[str, int]], attributes: Mapping[str, frozenset[str]]
) -> tuple[Overlap, ...]:
    """Every attribute's overlap with one column, best first: by the share of
    records covered, then Jaccard, then key — a total, deterministic order."""
    scores = [_overlap(cells, key, codes) for key, codes in attributes.items()]
    return tuple(sorted(scores, key=lambda o: (-o.records_contained, -o.jaccard, o.attribute_key)))


def _clear_winner(ranked: Sequence[Overlap]) -> Overlap | None:
    """The one attribute that covers the column and beats every other one
    that also does on Jaccard. A tie is no suggestion: a coin flip is not a
    proposal."""
    covering = sorted((o for o in ranked if o.covers), key=lambda o: (-o.jaccard, o.attribute_key))
    if not covering:
        return None
    if len(covering) > 1 and covering[1].jaccard >= covering[0].jaccard:
        return None
    return covering[0]


def _overlap(cells: Sequence[tuple[str, int]], key: str, codes: frozenset[str]) -> Overlap:
    values = {value for value, _ in cells}
    records = sum(count for _, count in cells)
    inside = values & codes
    union = values | codes
    return Overlap(
        attribute_key=key,
        contained=len(inside),
        distinct=len(values),
        records_contained=(
            sum(count for value, count in cells if value in codes) / records if records else 0.0
        ),
        jaccard=len(inside) / len(union) if union else 0.0,
    )
