from uuid import UUID

from fastapi import APIRouter, Body

import server.internal.telephonist as _internal
from server.models.telephonist import Application, ApplicationTask

tasks_router = APIRouter(prefix="/tasks")


def _detailed_task_view(task: ApplicationTask, app: Application):
    data = task.dict(by_alias=True, exclude={"app_id"})
    data["app"] = app.dict(
        by_alias=True, include={"id", "name", "display_name"}
    )
    return data


@tasks_router.get("/{task_id}")
async def get_task(task_id: UUID):
    task = await _internal.get_task_or_404(task_id)
    app = await Application.get_not_deleted(task.app_id)
    assert app, "application must exist"
    return _detailed_task_view(task, app)


@tasks_router.get("/{app_name}/{name}")
async def get_task_by_qualified_name(app_name: str, name: str):
    task = await _internal.get_task_or_404(f"{app_name}/{name}")
    app = await Application.get_not_deleted(task.app_id)
    assert app, "application must exist"
    return _detailed_task_view(task, app)


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
    await _internal.apply_application_task_update(task, update)
    return _detailed_task_view(task, app)
