from typing import Any, Dict, List
from uuid import UUID

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Body, HTTPException
from starlette.requests import Request

import server.internal.telephonist as _internal
from server.internal.telephonist import realtime
from server.models.common import AppBaseModel
from server.models.telephonist import ApplicationTask
from server.routes.telephonist.application_api._utils import APPLICATION

rest_router = APIRouter(dependencies=[APPLICATION])


@rest_router.get("/probe")
async def probe():
    return {"detail": "ok"}


@rest_router.get("/self")
async def get_self(app=APPLICATION):
    return app


class TaskView(_internal.DefinedTask):
    qualified_name: str


@rest_router.get("/defined-tasks")
async def get_tasks(app=APPLICATION):
    tasks = (
        await ApplicationTask.not_deleted()
        .find(ApplicationTask.app_id == app.id)
        .project(TaskView)
        .to_list()
    )
    return tasks


@rest_router.post("/defined-tasks")
async def define_app_task(
    app=APPLICATION, body: _internal.DefineTask = Body(...)
):
    task = _internal.define_application_task(app, body)
    return task


class DefinedTaskConfig(AppBaseModel):
    tasks: List[_internal.DefinedTask]


@rest_router.post("/defined-tasks/synchronize")
async def synchronize_application_tasks(
    app=APPLICATION, body: DefinedTaskConfig = Body(...)
):
    return await _internal.sync_defined_tasks(app, body.tasks)


@rest_router.post("/defined-tasks/check")
async def find_defined_tasks(names: List[str] = Body(...), app=APPLICATION):
    tasks = (
        await ApplicationTask.not_deleted().find(In("name", names)).to_list()
    )
    taken = []
    belong_to_self = []
    for task in tasks:
        if task.app_id != app.id:
            taken.append(task.name)
        else:
            belong_to_self.append(task.name)

    return {
        "taken": taken,
        "belong_to_self": belong_to_self,
        "free": [
            t for t in names if t not in taken and t not in belong_to_self
        ],
    }


@rest_router.patch("/defined-tasks/{task_id}")
async def update_app_task(
    task_id: UUID, app=APPLICATION, update: _internal.TaskUpdate = Body(...)
):
    task = await _internal.get_task_or_404(app.id, task_id)
    await _internal.apply_application_task_update(task, update)
    return task


@rest_router.delete("/defined-tasks/{task_id}")
async def deactivate_task(task_id: UUID, app=APPLICATION):
    task = await _internal.get_task_or_404(app.id, task_id)
    await _internal.deactivate_application_task(task)
    return {"detail": "Application task has been deleted"}


@rest_router.post("/events/publish")
async def publish_event(
    request: Request,
    app=APPLICATION,
    event_request: _internal.EventDescriptor = Body(...),
):
    if realtime.is_reserved_event(event_request.name):
        raise HTTPException(
            422,
            f"event type '{event_request.name}' is reserved for internal use",
        )
    event = await _internal.make_and_validate_event(
        app.id, event_request, request.client.host
    )
    await _internal.publish_events(event)
    if event.sequence_id:
        await _internal.apply_sequence_updates_on_event(event)
    return {"detail": "Published"}


@rest_router.post("/sequences")
async def create_sequence(
    request: Request,
    app=APPLICATION,
    sequence: _internal.SequenceDescriptor = Body(...),
):
    sequence = await _internal.create_sequence(
        app.id, sequence, request.client.host
    )
    await _internal.notify_sequence(sequence)
    return sequence


@rest_router.post("/sequences/{sequence_id}/finish")
async def finish_sequence(
    request: Request,
    sequence_id: PydanticObjectId,
    app=APPLICATION,
    update: _internal.FinishSequence = Body(...),
):
    sequence = await _internal.get_sequence(sequence_id, app.id)
    await _internal.finish_sequence(sequence, update, request.client.host)
    await _internal.notify_sequence(sequence)
    return {"detail": "Sequence finished"}


@rest_router.post("/sequences/{sequence_id}/meta")
async def set_sequence_meta(
    sequence_id: PydanticObjectId,
    app=APPLICATION,
    new_meta: Dict[str, Any] = Body(...),
):
    sequence = await _internal.get_sequence(sequence_id, app.id)
    await _internal.set_sequence_meta(sequence, new_meta)
    return {"detail": "Sequence's meta has been updated"}