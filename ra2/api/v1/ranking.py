# STUB — bodies owned by U2 (feat/p4-api-presence-ranking). Not frozen.
"""`/api/v1/evaluations/{id}/ranking` — tab 3 (plan-phase-4.md §9).

Read-only, and derived: there is no endpoint that stores or invalidates a
ranking, because there is nothing stored to invalidate (sw-design.md §16.5).

A run where **every** feature is suppressed returns a well-formed "nothing
scoreable" payload rather than an empty list — an empty list is what a UI
renders as a blank table, and "no results" is a different fact from "not enough
data for results" (§16.7).

Thin translation only.
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import RankingServiceDep, ResultsServiceDep
from ra2.api.schemas import (
    RankingRowResponse,
    RankingTabResponse,
    SeparatingRowResponse,
)
from ra2.api.v1.results import descriptor_response
from ra2.domain.ids import EvaluationId
from ra2.services.errors import NotFoundError

__all__ = ["router"]

router = APIRouter(tags=["ranking"])


@router.get("/evaluations/{evaluation_id}/ranking")
async def ranking_tab(
    evaluation_id: str, service: RankingServiceDep, results: ResultsServiceDep
) -> RankingTabResponse:
    """Tab 3 — read-only, and derived.

    There is no endpoint that stores or invalidates a ranking, because there
    is nothing stored to invalidate (§16.5).

    A run where **every** feature is suppressed returns this shape with empty
    `rows` and a verdict saying so — never a bare empty list, which a UI
    renders as a blank table. "No results" and "not enough data for results"
    are different facts (§16.7).
    """
    try:
        view = await service.ranking_tab(EvaluationId(evaluation_id))
        statuses = await results.scoring_status(EvaluationId(evaluation_id))
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return RankingTabResponse(
        scored=any(s.is_scored for s in statuses),
        descriptor=descriptor_response(view.descriptor),
        rows=[
            RankingRowResponse(
                model_id=row.model_id,
                tag=row.tag,
                digest=row.digest,
                rank=row.rank,
                macro_f1=row.macro_f1,
                ci_low=row.ci_low,
                ci_high=row.ci_high,
                best=row.best,
                tied=row.tied,
                worse=row.worse,
                verdict=row.verdict,
                presence_rate=row.presence_rate,
                median_latency_ms=row.median_latency_ms,
                prompt_tokens=row.prompt_tokens,
                vram_bytes=row.vram_bytes,
            )
            for row in view.rows
        ],
        separating=[
            SeparatingRowResponse(
                feature_id=row.feature_id,
                name=row.name,
                source_label=row.source_label,
                n=row.n,
                f1_by_model=dict(row.f1_by_model),
                delta=row.delta,
                reading=row.reading,
            )
            for row in view.separating
        ],
        verdict_headline=view.verdict_headline,
        verdict_detail=view.verdict_detail,
        scored_feature_count=view.scored_feature_count,
        unscored_feature_count=view.unscored_feature_count,
    )
