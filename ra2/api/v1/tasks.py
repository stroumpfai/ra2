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
from ra2.domain.ids import TaskId

__all__ = ["router"]

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskProgressResponse)
async def get_task(task_id: str, runner: TaskRunnerDep) -> TaskProgressResponse:
    """The UI polls this with `ui.timer` for records-done/total and ETA."""
    try:
        progress = runner.progress(TaskId(task_id))
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"task not found: {task_id}"
        ) from None
    return TaskProgressResponse(
        task_id=progress.task_id,
        name=progress.name,
        status=progress.status,
        done=progress.done,
        total=progress.total,
        message=progress.message,
        error=progress.error,
    )
