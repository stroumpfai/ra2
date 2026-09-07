# FROZEN — see CONTRACTS.md
"""The `/api/v1` router. Frozen so C1 and C2 never touch the same file."""

from fastapi import APIRouter

from ra2.api.v1 import census, corpora, deliveries, tasks

__all__ = ["api_router"]

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(deliveries.router)
api_router.include_router(corpora.router)
api_router.include_router(census.router)
api_router.include_router(tasks.router)
