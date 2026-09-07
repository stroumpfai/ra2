# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Delivery validation: blocking and non-blocking (mvp-spec.md §4.3).

Uniqueness is checked **across the whole delivery**, not per file: the single
shared text file is the join target for every cantonal set, so a `UnfallUid`
collision between two cantons would silently attach one canton's narrative to
another canton's record.
"""

from collections.abc import Sequence

from ra2.domain.delivery import DeliveryAnalysis, FileAnalysis
from ra2.domain.findings import Finding

__all__ = ["validate_delivery"]


def validate_delivery(files: Sequence[FileAnalysis]) -> DeliveryAnalysis:
    """Cross-file validation over the **selected** files.

    Blocking: duplicate `UnfallUid`/`ObjektUid`/`PersonUid` across the whole
    delivery, orphan FKs, header mismatch.

    Reported: `AnzObjFeld` and `BeteiligtePersTotalFeld` count mismatches, text
    rows with no `unfall` row, `unfall` rows with no text, detected encodings.
    """
    raise NotImplementedError


def blocking_findings(analysis: DeliveryAnalysis) -> tuple[Finding, ...]:
    """The subset that must stop the freeze with nothing written."""
    raise NotImplementedError
