from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends

import server.common.actions as _internal
from server.common.models import Pagination
from server.database import (
    Application,
    ApplicationTask,
    Counter,
    EventSequence,
    EventSequenceState,
)

tasks_router = APIRouter(prefix="/tasks")


async def _get_task_view(task: ApplicationTask):
    app = await Application.get_not_deleted(task.app_id)
    assert app, "application must exist"
    data = task.dict(by_alias=True, exclude={"app_id"})
    data["stats"] = {
        "failed_in_24h": await EventSequence.find(
            EventSequence.task_id == task.id,
            EventSequence.state == EventSequenceState.FAILED,
            EventSequence.id
            > hex(int((datetime.now() - timedelta(days=1)).timestamp()))[2:]
            + "0000000000000000",
        ).count()
    }
    data["app"] = app.dict(
        by_alias=True, include={"id", "name", "display_name"}
    )
    return data


@tasks_router.get("/{task_id}")
async def get_task(task_id: UUID):
    return await _get_task_view(await _internal.get_task_or_404(task_id))


class TaskSequencesPagination(Pagination):
    ordered_by_options = {"_id", "state"}
    descending_by_default = True


@tasks_router.get("/{task_id}/sequences")
async def get_sequences(
    task_id: UUID,
    state: Optional[EventSequenceState] = None,
    pagination: TaskSequencesPagination = Depends(),
):
    condition = [EventSequence.task_id == task_id]
    if state is not None:
        condition.append(EventSequence.state == state)
    return {
        **(
            await pagination.paginate(
                EventSequence, filter_condition=condition
            )
        ).dict(by_alias=True),
        "counters": {
            "failed": await Counter.get_counter(
                f"failed_sequences/task/{task_id}"
            ),
            "finished": await Counter.get_counter(
                f"finished_sequences/task/{task_id}"
            ),
            "total": await Counter.get_counter(f"sequences/task/{task_id}"),
        },
    }


@tasks_router.get("/{app_name}/{name}")
async def get_task_by_qualified_name(app_name: str, name: str):
    return await _get_task_view(
        await _internal.get_task_or_404(f"{app_name}/{name}")
    )


@tasks_router.delete("/{task_id}")
async def deactivate_task(task_id: UUID):
    task = await _internal.get_task_or_404(task_id)
    await _internal.deactivate_application_task(task)
    return {"detail": f"Task {task_id} has been deactivated"}


@tasks_router.patch("/{task_id}")
async def update_task(
    task_id: UUID,
    update: _internal.TaskUpdate = Body(...),
):
    task = await _internal.get_task_or_404(task_id)
    app = await Application.get(task.app_id)
    assert app, "app not found"  # app must exist
    task = await _internal.apply_application_task_update(task, update)
    await _internal.notify_task_changed(task)
    return {"detail": "Task has been updated"}
