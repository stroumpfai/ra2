# FROZEN — see CONTRACTS.md
"""The `/api/v1` router. Frozen so no two router agents touch the same file."""

from fastapi import APIRouter

from ra2.api.v1 import (
    census,
    codelists,
    corpora,
    deliveries,
    evaluations,
    features,
    mismatches,
    models,
    presence,
    prompt_templates,
    ranking,
    results,
    runs,
    tasks,
)

__all__ = ["api_router"]

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(deliveries.router)
api_router.include_router(corpora.router)
api_router.include_router(census.router)
api_router.include_router(tasks.router)
api_router.include_router(codelists.router)
api_router.include_router(features.router)
api_router.include_router(prompt_templates.router)
api_router.include_router(evaluations.router)
api_router.include_router(runs.router)
api_router.include_router(models.router)
api_router.include_router(results.router)
api_router.include_router(presence.router)
api_router.include_router(ranking.router)
api_router.include_router(mismatches.router)
