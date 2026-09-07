# STUB — bodies owned by C2 (feat/m4-api-census). Not frozen.
"""`/api/v1/tasks/{id}` — background job progress (sw-design.md §9).

This is the one place `ra2/api/` reaches into `ra2/infra/`, and it reaches only
for the `TaskRunner` **protocol** — there is no service in front of the task
runner and inventing one would buy nothing. The exception is declared
explicitly in `.importlinter`; adapters stay out of reach.
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import TaskRunnerDep
from ra2.api.schemas import TaskProgressResponse

__all__ = ["router"]

router = APIRouter(prefix="/tasks", tags=["tasks"])

_NOT_BUILT = "not implemented until M4 (C2)"


@router.get("/{task_id}", response_model=TaskProgressResponse)
async def get_task(task_id: str, runner: TaskRunnerDep) -> TaskProgressResponse:
    """The UI polls this with `ui.timer` for records-done/total and ETA."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)
