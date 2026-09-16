# STUB — bodies owned by T1 (feat/p4-scoring-service). Not frozen.
"""The scoring pass (sw-design.md §16.1, §16.6).

A score is not computed when someone looks at it. It is computed once, by a
job, into `score` and `mismatch` rows, and everything the three Results tabs
render is a read over those rows.

**One `(run, feature)`, one commit.** Every `score` row for that pair — the
all-languages row and each per-language row, every metric — plus every
`mismatch` row that feature produced, are written together. Nothing batches
across features, and no transaction is held open across the EAV read that feeds
the next one. This is §15.3's rule one level up and it buys the same property:
**the features of a run with no `score` rows are the work left**, which is a
query rather than bookkeeping.

**No status column.** `status()` derives `ScoringStatus` by counting; see
`services/protocols.py`.

Implements `Scorer` (`services/protocols.py`) via `status()` — T2 and T3 are
handed this class as that protocol and never import it directly, the same seam
`PromptResolver` gave phase 3.

**M27 freezes the constructor and the signatures. T1 writes the bodies.**
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import RunId
from ra2.infra.clock import Clock
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import TaskRunner
from ra2.services.protocols import GroundTruthProvider, ScoringStatus

__all__ = ["ScoringService"]


class ScoringService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ground_truth: GroundTruthProvider,
        task_runner: TaskRunner,
        clock: Clock,
        id_factory: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._ground_truth = ground_truth
        self._task_runner = task_runner
        self._clock = clock
        self._id_factory = id_factory

    async def score_run(self, run_id: RunId) -> None:
        """Score one finished run, feature by feature, committing each.

        **Chained off the run worker's terminal `done`**, not triggered by a
        button (`SD17`): every input a score depends on is immutable from the
        launch commit onward, so there is no moment in between where a user
        could make a meaningful decision, and the design draws no such control.

        A `failed` or `interrupted` run raises `RunNotScoreableError` and is
        never scored — a partial corpus produces real-looking numbers over an
        unstated denominator.

        **Resume is implicit.** Re-entering after an interruption scores only
        the features with no rows, because that is what "the work left" means
        here. No separate `resume` entry point exists, and that is deliberate:
        one that skipped the same query would be a second answer to "how far
        did it get".
        """
        raise NotImplementedError

    async def rescore_run(self, run_id: RunId) -> None:
        """Re-score every feature of a run, **preserving analyst tags**.

        The explicit path, and the only reason it exists is that the *scorer's
        own code* can change; no other input can. Per feature it replaces the
        `score` rows — they are a pure function of immutable inputs, so a
        re-score either reproduces them byte-for-byte or the code changed, and
        replacement is correct either way — and **upserts** the `mismatch` rows
        on `(run_id, record_id, feature_id)`, rewriting the derived columns and
        leaving `analyst_tag`, `tagged_at` and `note` alone.

        `DELETE`-then-`INSERT` is the obvious implementation and it destroys
        review work silently, at the moment a developer is most confident
        (§16.6, SD21, R5).
        """
        raise NotImplementedError

    async def status(self, session: AsyncSession, run_id: RunId) -> ScoringStatus:
        """`Scorer`. Derived from committed rows, never from a column."""
        raise NotImplementedError
