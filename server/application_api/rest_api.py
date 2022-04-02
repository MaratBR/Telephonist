from typing import Any, List, Optional
from uuid import UUID

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Body, HTTPException, Query
from starlette.requests import Request

import server.common.internal.application as application_internal
import server.common.internal.events as event_internal
from server.application_api._utils import APPLICATION
from server.common.channels import get_channel_layer
from server.common.models import AppBaseModel
from server.common.transit import dispatch
from server.database import ApplicationTask, EventSequence, OneTimeSecurityCode

rest_router = APIRouter()

async def _get_sequence_or_404(
    sequence_id: PydanticObjectId, app_id: Optional[PydanticObjectId] = None
):
    sequence = await EventSequence.get(sequence_id)
    if sequence is None:
        raise HTTPException(
            404, f"Sequence with id = {sequence_id} does not exist"
        )
    if app_id and sequence.app_id != app_id:
        raise HTTPException(
            401,
            f"Sequence with id = {sequence_id} does not belong to application"
            f" with id = {app_id}",
        )
    return sequence


@rest_router.get("/probe")
async def probe():
    return {"detail": "ok"}


@rest_router.get("/self", dependencies=[APPLICATION])
async def get_self(app=APPLICATION):
    return app


@rest_router.post("/cr")
async def code_registration(code: str = Query(...), body: application_internal.CreateApplication = Body(...)):
    body.disabled = False
    code = await OneTimeSecurityCode.get_valid_code("new_app", code)
    if code is None:
        raise HTTPException(401, "Invalid or expired registration code")
    application = await application_internal.create_new_application(body)
    await get_channel_layer().group_send(
        f"m/cr/{code}",
        "cr_complete",
        {"cr": code, "app_id": application.id, "app_name": application.name}
    )
    return {
        "detail": "Application registered successfully!",
        "key": application.access_key,
        "_id": application.id
    }


class TaskView(application_internal.DefinedTask):
    qualified_name: str


@rest_router.get("/defined-tasks", dependencies=[APPLICATION])
async def get_tasks(app=APPLICATION):
    tasks = (
        await ApplicationTask.not_deleted()
        .find(ApplicationTask.app_id == app.id)
        .project(TaskView)
        .to_list()
    )
    return tasks


@rest_router.post("/defined-tasks", dependencies=[APPLICATION])
async def define_task_route(
    app=APPLICATION, body: application_internal.DefineTask = Body(...)
):
    task = await application_internal.define_task(app, body)
    await application_internal.notify_task_changed(task)
    return task


class DefinedTaskConfig(AppBaseModel):
    tasks: List[application_internal.DefinedTask]


@rest_router.post("/defined-tasks/synchronize", dependencies=[APPLICATION])
async def sync_tasks_route(
    app=APPLICATION, body: DefinedTaskConfig = Body(...)
):
    return await application_internal.sync_tasks(app, body.tasks)


@rest_router.post("/defined-tasks/check", dependencies=[APPLICATION])
async def find_defined_tasks_route(
    names: List[str] = Body(...), app=APPLICATION
):
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


@rest_router.patch("/defined-tasks/{task_id}", dependencies=[APPLICATION])
async def update_task_route(
    task_id: UUID,
    app=APPLICATION,
    update: application_internal.TaskUpdate = Body(...),
):
    task = await application_internal.get_task_or_404(task_id)
    if task.app_id != app.id:
        raise HTTPException(
            401,
            "cannot update the task that belongs to a different applications",
        )
    await application_internal.apply_application_task_update(task, update)
    return task


@rest_router.delete("/defined-tasks/{task_id}", dependencies=[APPLICATION])
async def deactivate_task_route(task_id: UUID, app=APPLICATION):
    task = await application_internal.get_task_or_404(task_id)
    if task.app_id != app.id:
        raise HTTPException(
            401,
            "cannot deactivated the task that belongs to a different"
            " applications",
        )
    await application_internal.deactivate_application_task(task)
    return {"detail": "Application task has been deleted"}


@rest_router.post("/events/publish", dependencies=[APPLICATION])
async def publish_event_route(
    request: Request,
    app=APPLICATION,
    event_request: event_internal.EventDescriptor = Body(...),
):
    if event_internal.is_reserved_event(event_request.name):
        raise HTTPException(
            422,
            f"event type '{event_request.name}' is reserved for internal use",
        )
    event = await event_internal.create_event(
        app, event_request, request.client.host
    )
    await event_internal.notify_events(event)
    if event.sequence_id:
        await event_internal.apply_sequence_updates_on_event(event)
    return {"detail": "Published"}


@rest_router.post("/sequences", dependencies=[APPLICATION])
async def create_sequence_route(
    request: Request,
    app=APPLICATION,
    descriptor: event_internal.SequenceDescriptor = Body(...),
):
    (
        sequence,
        start_event,
    ) = await event_internal.create_sequence_and_start_event(
        app.id, descriptor, request.client.host
    )
    await dispatch(
        event_internal.SequenceCreated(
            sequence_id=sequence.id,
            app_id=sequence.app_id,
            task_id=sequence.task_id,
        )
    )
    await event_internal.notify_events(start_event)
    return sequence


@rest_router.post("/sequences/{sequence_id}/finish", dependencies=[APPLICATION])
async def finish_sequence(
    request: Request,
    sequence_id: PydanticObjectId,
    app=APPLICATION,
    update: event_internal.FinishSequence = Body(...),
):
    sequence = await _get_sequence_or_404(sequence_id, app.id)
    events = await event_internal.finish_sequence(
        sequence, update, request.client.host
    )
    await event_internal.notify_events(*events)
    await dispatch(
        event_internal.SequenceFinished(
            sequence_id=sequence.id,
            app_id=sequence.app_id,
            task_id=sequence.task_id,
            is_skipped=False,
        )
    )
    return {"detail": "Sequence finished"}


@rest_router.post("/sequences/{sequence_id}/meta", dependencies=[APPLICATION])
async def set_sequence_meta_route(
    sequence_id: PydanticObjectId,
    app=APPLICATION,
    new_meta: dict[str, Any] = Body(...),
):
    sequence = await _get_sequence_or_404(sequence_id, app.id)
    await sequence.update_meta(new_meta)
    await dispatch(event_internal.SequenceUpdated(sequence=sequence))
    return {"detail": "Sequence's meta has been updated"}
