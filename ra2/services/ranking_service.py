# STUB — bodies owned by T3 (feat/p4-ranking-service). Not frozen.
"""Tab 3 (sw-design.md §16.5).

**Every number here is derived from tab 1's scored rows.** This service reads
the same `score` rows `ResultsService` reads and hands them to
`domain/ranking.py`; nothing is stored, nothing is cached independently, and if
this and the extraction tab disagree then this one is wrong by construction.
J13 asserts exactly that, in the browser.

Three columns are **reported, never scored** — median latency, prompt tokens
and VRAM — per the design's own rule 4, "the tie-breaker you apply, not one the
tool applies". **The presence rate joins them** (`SD20`): mvp-spec.md §11.2 is
unambiguous that presence has no independent gold label, and a model that flags
everything present maximises it. A test asserts the negative — change the
presence rate and the ranking must not move.

**M27 freezes the constructor and the signature. T3 writes the body.**
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import EvaluationId
from ra2.services.protocols import Scorer
from ra2.services.readmodels import RankingTabView

__all__ = ["RankingService"]


class RankingService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        scorer: Scorer,
    ) -> None:
        self._session_factory = session_factory
        self._scorer = scorer

    async def ranking_tab(self, evaluation_id: EvaluationId) -> RankingTabView:
        """The ranking table, the separating features and the verdict.

        Raises nothing when the models tie everywhere: an empty `separating` is
        a **result** — "this run does not separate them" — and the verdict is
        composed from the computed ranks rather than authored.

        Renders the "nothing scoreable" state rather than a blank table when
        every feature is suppressed: `domain.ranking.rank_models` raises there,
        because there is no macro of nothing and a `0.0` prints as a model that
        scored zero (§16.4).
        """
        raise NotImplementedError
