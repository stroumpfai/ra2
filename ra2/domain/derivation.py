# FROZEN (types and signatures) — see CONTRACTS.md
"""The derived-aggregate evaluator (mvp-spec.md §8.3).

**This module is `plan-phase-2.md` Q1's deferral coming due.** Phase 2 stored
`derivation_json` and declined to execute it, on the explicit reasoning that
"scoring (phase 3) needs to build one anyway — building it twice is waste".
Phase 3 did not need it: a derivation reaches a prompt as a *description*.
Scoring needs it, because a derived feature's **ground truth does not exist
anywhere** until something computes it (sw-design.md §16.2).

It is pure, and it takes a `RecordProjection` rather than a session: the closed
catalogue is testable without a database, and the EAV read stays in
`persistence/` where §1.1 requires it.

Pure — no SQLAlchemy, no session (sw-design.md §16.8).

**M27 freezes the types and the signature. S3 writes the bodies.**
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ra2.domain.feature import DerivationSpec

__all__ = ["DerivationError", "RecordProjection", "evaluate"]


@dataclass(frozen=True, slots=True)
class RecordProjection:
    """One record's `objekt` and `person` cells, as plain data.

    One mapping per row, `column_name -> value_raw`. A column absent from a
    mapping and a column present with an empty value are **not** the same
    thing, and the operators treat them differently: `IS_EMPTY` is true for
    both, `EQ` is false for both, and nothing silently invents a value for a
    missing column.

    `person_rows` are flattened across their parent `objekt` rows. `person`
    hangs off `objekt`, never off `unfall` (mvp-spec.md §4.1), but no
    derivation in the catalogue reaches across that edge: `count_persons` and
    `any_person_matches` are record-wide, so carrying the tree here would be
    structure nothing reads.
    """

    objekt_rows: Sequence[Mapping[str, str]]
    person_rows: Sequence[Mapping[str, str]]


class DerivationError(Exception):
    """A derivation that cannot be evaluated against this projection.

    The one case that reaches it in practice is an ordinal whose observed code
    is absent from `ordered_codes` — the feature config declared an ordering
    and the data contains something outside it. That is a **configuration**
    fault, not a record fault, so it raises rather than resolving to `None`:
    silently skipping the row would drop a record from the denominator and make
    a feature look better measured than it is (Do-NOT #6's reasoning, applied
    to ground truth).
    """


def evaluate(derivation: DerivationSpec, projection: RecordProjection) -> str | None:
    """This record's ground-truth value for one derived feature.

    Returns a **string**, because that is what it is compared against:
    `extraction_value.value_normalised` is a string, and `domain/matching.py`
    normalises both sides the same way. Counts render as decimal integers,
    booleans as `"true"` / `"false"`, ordinals as the code itself.

    Returns `None` only when the derivation genuinely has no value for this
    record — `MAX_ORDINAL` over a record with no rows in the named table. That
    `None` means "not a labelled case" and the record leaves the denominator,
    exactly as an empty source column does (§8.6).

    **A count over zero rows is `"0"`, not `None`.** It is the single most
    consequential line in this module: "no objects" is a fact the data states
    and belongs in the denominator, while "no value" is a fact the data is
    missing and does not. Getting it backwards changes every derived feature's
    `n` (sw-design.md §16.2).

    Raises `DerivationError` for a configuration fault; never for a data one.
    """
    raise NotImplementedError
