# STUB — bodies owned by T2 (feat/p4-results-service). Not frozen.
"""Tabs 1 and 2 (sw-design.md §16.7).

Reads `score` and `mismatch` rows and assembles the read models. **This is
where suppression is applied** — every cell is computed and stored by T1, and
this layer substitutes `SuppressedCell` when `n < evaluation.min_cell_count`
(`SD19`). Two things follow, and both are the point: changing the floor never
requires a re-score, and a suppressed cell is a shape carrying its `n` rather
than a number, an empty string or a `None`.

Two invariants this module must not lose:

- **Suppressed rows sort last, in both directions** — never as `0`. A
  suppressed row sorting as zero silently ranks the least-evidenced feature as
  the worst-performing one (R7).
- **Goal 2 numbers never travel without their Goal 1 companions** (§11.2). The
  read model makes that a type error (`PresenceRow.goal1`), but the query has
  to fetch them, and a "just the rates" shortcut is the thing not to add.

**M27 freezes the constructor and the signatures. T2 writes the bodies.**
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import EvaluationId, FeatureId, RunId
from ra2.services.protocols import Scorer
from ra2.services.readmodels import (
    BreakdownView,
    ByLanguageView,
    ExtractionTabView,
    PresenceTabView,
    ScoringStatusView,
    SortDir,
)

__all__ = ["ResultsService"]


class ResultsService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        scorer: Scorer,
    ) -> None:
        self._session_factory = session_factory
        self._scorer = scorer

    async def scoring_status(self, evaluation_id: EvaluationId) -> tuple[ScoringStatusView, ...]:
        """One status per run — which of §16.7's three states each tab renders."""
        raise NotImplementedError

    async def extraction_tab(
        self,
        evaluation_id: EvaluationId,
        *,
        page: int = 1,
        page_size: int = 10,
        sort_key: str = "name",
        sort_dir: SortDir = SortDir.ASC,
        expanded_feature_id: FeatureId | None = None,
        by_language_feature_id: FeatureId | None = None,
        by_language_model_id: str | None = None,
    ) -> ExtractionTabView:
        """Tab 1. Suppressed rows sort **last** whichever way `sort_dir` points."""
        raise NotImplementedError

    async def breakdown(self, run_ids: tuple[RunId, ...], feature_id: FeatureId) -> BreakdownView:
        """The expanded row: P · R · F1 · hit · wrong · missing per model."""
        raise NotImplementedError

    async def by_language(self, run_id: RunId, feature_id: FeatureId) -> ByLanguageView:
        """One feature × model across languages, with the standing encoding
        caveat this breakdown may never be shown without (mvp-spec.md §13)."""
        raise NotImplementedError

    async def presence_tab(
        self,
        evaluation_id: EvaluationId,
        *,
        model_id: str | None = None,
        feature_key: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PresenceTabView:
        """Tab 2, one model at a time. `model_id=None` picks the first run's."""
        raise NotImplementedError
