# STUB — bodies owned by Y1 (feat/p5-mismatch-service). Not frozen.
"""Mismatch review (mvp-spec.md §12, sw-design.md §17).

The list, the tag, the tally and the export rows. **The first service in this
codebase through which a human writes to the database**, and every rule below
follows from that sentence.

**This module imports nothing from `scoring_service` or `ranking_service`, and
that is the contract.** `mvp-spec.md` §12: *"The tag never feeds back into a
metric. Nothing is rescored."* The absence of the edge is what makes it true —
a rule nobody can violate beats a rule everybody remembers, and this one would
be invisible once violated, because a number that moved because of a tag is
not visibly wrong (§17.3, R3). `tests/test_p5_contract.py` asserts the absence
on this module's AST.

**It writes three columns.** `analyst_tag`, `tagged_at` and `note` are review's
half of `mismatch`; `record_value`, `extracted_value` and `evidence_span` are
the scorer's and are never touched here (§17.1). The mirror of that obligation
— the tag-preserving upsert — has been built and tested since phase 4
(`SD21`).

**One run at a time** (§17.6, `SD26`). `list_mismatches` resolves an
evaluation to one of its runs the same way `ResultsService.presence_records`
resolves one model, and there is no "all runs" scope to represent.

**M35 freezes the constructor and the signatures. Y1 writes the bodies.**
"""

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import EvaluationId, FeatureId, MismatchId, RunId
from ra2.domain.mismatch import MismatchTag, ReviewTally, TagFilter, TagState
from ra2.infra.clock import Clock
from ra2.services.readmodels import MismatchListView, MismatchRowView, SortDir

__all__ = ["MismatchService"]


class MismatchService:
    """Implements `services.protocols.MismatchTally` (structurally — no
    Results surface imports this module)."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def list_mismatches(
        self,
        evaluation_id: EvaluationId,
        *,
        run_id: RunId | None = None,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter = TagState.ANY,
        sort_key: str = "feature",
        sort_dir: SortDir = SortDir.ASC,
        page: int = 1,
        page_size: int = 25,
    ) -> MismatchListView:
        """The whole screen for one run of one evaluation.

        `run_id=None` picks the evaluation's first run, the resolution
        `ResultsService.presence_records` already uses — there is no "all runs"
        option, because a mixed list is the cross-model agreement §16.9 defers
        (§17.6).

        The tallies it returns are scoped to the **same filters** as the rows,
        so the strip under the table can never disagree with the table.
        """
        raise NotImplementedError

    async def tag(
        self,
        mismatch_id: MismatchId,
        *,
        tag: MismatchTag,
        note: str | None = None,
    ) -> MismatchRowView:
        """Write one analyst's judgement, and stamp `tagged_at`.

        **Idempotent**: the same tag twice leaves one row. Re-tagging restamps,
        because the second judgement is the current one (Q4 — a judgement made
        on the wrong row must be correctable, or the first mis-click is
        permanent in the one table a human writes to).

        The parameter is a `MismatchTag`, not a `str`: the column is open so a
        fourth tag needs no migration, but nothing in this codebase may *write*
        a value outside the three (`SD24`, §17.5).

        **Changes no `score` row.** There is no path from here to scoring, and
        the test that proves it records every `score` row, tags every mismatch
        and re-reads them byte-identically.
        """
        raise NotImplementedError

    async def clear_tag(self, mismatch_id: MismatchId) -> MismatchRowView:
        """Remove the tag, **and `tagged_at` with it** (Q4).

        A cleared row that kept its timestamp would read as reviewed in the
        `Reviewed` column while counting as untagged in the tally. `note` is
        cleared too: it annotated a judgement that no longer exists.
        """
        raise NotImplementedError

    async def tally(self, session: AsyncSession, run_id: RunId) -> Mapping[FeatureId, ReviewTally]:
        """`services.protocols.MismatchTally` — per-feature review counts.

        Takes the session because the caller owns the transaction boundary,
        like every other protocol in that module. **Returns counts and nothing
        else**; there is deliberately no sibling that could influence a score.
        """
        raise NotImplementedError

    async def export_rows(
        self,
        evaluation_id: EvaluationId,
        *,
        run_id: RunId | None = None,
        feature_id: FeatureId | None = None,
        tag_state: TagFilter = TagState.ANY,
        sort_key: str = "feature",
        sort_dir: SortDir = SortDir.ASC,
    ) -> MismatchListView:
        """The same list, **unpaged**, for the CSV.

        A separate entry point rather than a `page_size=None` flag on
        `list_mismatches`, so an export cannot be produced by accident and the
        one that is produced carries the same view — the same descriptor, the
        same run, the same filters — as the screen it was exported from
        (`P4-D3`, sw-design.md §7).
        """
        raise NotImplementedError
