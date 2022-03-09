from datetime import datetime, timedelta
from uuid import UUID

from beanie.odm.enums import SortDirection
from fastapi import APIRouter, Body, Depends

import server.internal.telephonist as _internal
from server.models.common import Pagination
from server.models.telephonist import (
    Application,
    ApplicationTask,
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


@tasks_router.get("/{task_id}/sequences")
async def get_sequences(pagination: TaskSequencesPagination = Depends()):
    sequences = (
        await EventSequence.find(EventSequence.task_id == task_id)
        .sort(("_id", SortDirection.DESCENDING))
        .limit(20)
        .to_list()
    )
    return sequences


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
