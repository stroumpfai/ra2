# STUB — bodies owned by H3 (feat/p3-persistence). Not frozen.
"""Evaluation drafts, the launch transaction and the `evaluation_feature`
snapshot (mvp-spec.md §9, sw-design.md §15.2).

**An evaluation is mutable while `launched_at IS NULL`** — unlike `corpus` or
`extraction`, a draft's six setup steps are edited in place, not appended.
`get()` returns the ORM row and callers mutate its columns directly, then
flush through their own session — the same convention
`FeatureRepository.get_config()` follows for a draft `feature_config`.

`launch()` is the one method that touches more than one table: it writes the
`evaluation_feature` snapshot, creates the runs and stamps `is_dev` /
`launched_at`, all in **one flush**. This is the persistence half of "an
evaluation pins; a launch snapshots" (sw-design.md §15.2) — verifying the
cited `feature_config` is frozen, resolving every fingerprint and building
the `Run` rows (provenance and all) is `EvaluationService.launch`'s job
(Wave 2, I2); this repository does not re-check any of it, and it is the
caller's `session_scope` that commits the whole thing or rolls it back.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ra2.domain.ids import EvaluationId
from ra2.persistence.models import Evaluation, EvaluationFeature, Run

__all__ = ["EvaluationRepository"]


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_draft(self, evaluation: Evaluation) -> None:
        self._session.add(evaluation)
        await self._session.flush()

    async def get(self, evaluation_id: EvaluationId) -> Evaluation | None:
        stmt = (
            select(Evaluation)
            .where(Evaluation.id == evaluation_id)
            .options(selectinload(Evaluation.features), selectinload(Evaluation.runs))
        )
        result: Evaluation | None = await self._session.scalar(stmt)
        return result

    async def list_all(self) -> list[Evaluation]:
        """Every evaluation, drafts included, newest first."""
        stmt = select(Evaluation).order_by(Evaluation.created_at.desc())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def launch(
        self,
        evaluation: Evaluation,
        *,
        features: Sequence[EvaluationFeature],
        runs: Sequence[Run],
        is_dev: bool,
        launched_at: datetime,
    ) -> None:
        """The launch transaction's persistence half (sw-design.md §15.2).

        In one flush: writes the `evaluation_feature` snapshot rows, creates
        one `run` per selected model, and stamps `is_dev` / `launched_at` on
        the existing `evaluation` row. `evaluation` must be the same instance
        `get()` returned in this session — this method mutates it in place
        rather than re-fetching it, so a caller that already holds it (to
        have read `feature_config_id` off it, say) is not paying for a
        second round trip.

        Nothing here checks that the cited `feature_config` is frozen, that
        `features`/`runs` are non-empty, or that `evaluation.launched_at` was
        already `None` — those are `EvaluationService.launch`'s
        responsibility (`FeatureValidationError` / `EvaluationLockedError`).
        This method is the atomic write once the caller has decided all of
        that; "in one transaction" (§15.2) is true because every write below
        shares this one flush and the caller's `session_scope` is what
        commits or rolls it all back together.
        """
        evaluation.is_dev = is_dev
        evaluation.launched_at = launched_at
        for feature in features:
            self._session.add(feature)
        for run in runs:
            self._session.add(run)
        await self._session.flush()

    # --- discard (sw-design.md §18) ----------------------------------------

    async def delete(self, evaluation: Evaluation) -> None:
        """Remove the evaluation, its `evaluation_feature` snapshot and its
        runs — all three by `ondelete="CASCADE"` (§18.1).

        What the evaluation **cites** is `RESTRICT` and stays: the corpus, the
        feature config and every prompt version. Discarding an evaluation is
        not a way to delete a corpus.
        """
        await self._session.delete(evaluation)
        await self._session.flush()
