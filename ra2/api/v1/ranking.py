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

from fastapi import APIRouter

__all__ = ["router"]

router = APIRouter(tags=["ranking"])
