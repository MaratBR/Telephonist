from datetime import timezone
from typing import List, Optional

import fastapi
from beanie import PydanticObjectId
from beanie.odm.enums import SortDirection
from bson.errors import InvalidId
from fastapi import Body, Depends, HTTPException, Query
from starlette import status
from starlette.requests import Request
from starlette.responses import Response

import server.common.actions.application as _internal
from server.common.actions.utils import Errors
from server.common.channels import get_channel_layer
from server.common.models import (
    AppBaseModel,
    IdProjection,
    Pagination,
    PaginationResult,
)
from server.database import (
    Application,
    ApplicationTask,
    ApplicationView,
    AppLog,
    ConnectionInfo,
    EventSequence,
    EventSequenceState,
    OneTimeSecurityCode,
)

_APPLICATION_NOT_FOUND = "Application not found"


async def _get_application(app_id_or_name: str):
    try:
        app_id_or_name = PydanticObjectId(app_id_or_name)
    except InvalidId:
        pass
    return Errors.raise404_if_none(
        await Application.find_one(
            Application.NOT_DELETED_COND,
            {"_id": app_id_or_name}
            if isinstance(app_id_or_name, PydanticObjectId)
            else {"name": app_id_or_name},
        ),
        f'Application with "{app_id_or_name}" not found',
    )


applications_router = fastapi.APIRouter(prefix="/applications")


class ApplicationsPagination(Pagination):
    ordered_by_options = {"name", "_id"}


@applications_router.get(
    "",
    responses={200: {"model": PaginationResult[ApplicationView]}},
)
async def get_applications(
    args: ApplicationsPagination = Depends(),
) -> PaginationResult[ApplicationView]:
    return await args.paginate(Application, ApplicationView)


@applications_router.post(
    "", status_code=201, responses={201: {"model": IdProjection}}
)
async def create_application(body: _internal.CreateApplication = Body(...)):
    app = await _internal.create_new_application(body)
    return ApplicationView(**app.dict(by_alias=True))


@applications_router.get("/check-if-name-taken")
async def check_if_application_name_taken(name: str = Query(...)):
    return (
        await Application.not_deleted().find(Application.name == name).exists()
    )


class SequenceLogs(AppBaseModel):
    sequence_id: PydanticObjectId
    logs: List[AppLog]


@applications_router.get("/{app_id_or_name}")
async def get_application(app_id_or_name: str):
    app = await _get_application(app_id_or_name)
    connections = (
        await ConnectionInfo.find(ConnectionInfo.app_id == app.id)
        .sort(("connected_at", SortDirection.DESCENDING))
        .to_list()
    )
    tasks: list[ApplicationTask] = (
        await ApplicationTask.not_deleted()
        .find(ApplicationTask.app_id == app.id)
        .to_list()
    )
    in_progress_sequences = (
        await EventSequence.find(
            EventSequence.app_id == app.id,
            EventSequence.state == EventSequenceState.IN_PROGRESS,
        )
        .sort(("_id", SortDirection.DESCENDING))
        .to_list()
    )
    if len(in_progress_sequences) < 50:
        completed_sequences = (
            await EventSequence.find(
                EventSequence.app_id == app.id,
                EventSequence.state != EventSequenceState.IN_PROGRESS,
            )
            .sort(("_id", SortDirection.DESCENDING))
            .limit(50 - len(in_progress_sequences))
            .to_list()
        )
    else:
        completed_sequences = []

    async def get_task_info(task: ApplicationTask):
        ongoing_sequences_count = await EventSequence.find(
            EventSequence.task_id == task.id,
            EventSequence.state == EventSequenceState.IN_PROGRESS,
        ).count()
        last_sequence: EventSequence = await (
            EventSequence.find(EventSequence.task_id == task.id)
            .sort(("created_at", SortDirection.DESCENDING))
            .limit(1)
            .to_list()
        )
        last_sequence = (
            last_sequence[0].dict(
                by_alias=True,
                include={
                    "id",
                    "state",
                    "error",
                    "name",
                    "created_at",
                    "connection_id",
                },
            )
            if len(last_sequence) == 1
            else None
        )

        return {
            "ongoing": ongoing_sequences_count,
            "last_sequence": last_sequence,
        }

    return {
        "app": app,
        "connections": connections,
        "tasks": [
            {**t.dict(by_alias=True), "sequence_info": await get_task_info(t)}
            for t in tasks
        ],
        "sequences": {
            "completed": completed_sequences,
            "in_progress": in_progress_sequences,
        },
    }


@applications_router.patch("/{app_id}")
async def update_application(
    app_id: PydanticObjectId, update: _internal.ApplicationUpdate = Body(...)
):
    app = await _get_application(app_id)
    app.display_name = (
        app.display_name
        if update.display_name is None
        else update.display_name
    )
    app.description = (
        app.description if update.description is None else update.description
    )
    app.tags = app.tags if update.tags is None else update.tags
    if update.disabled is not None and update.disabled != app.disabled:
        if update.disabled:
            # TODO send message to the application and to the user
            pass
        app.disabled = update.disabled
    await app.save_changes()
    return ApplicationView(**app.dict(by_alias=True))


@applications_router.delete("/{app_id}")
async def deactivate_application(app_id: str):
    app = await _get_application(app_id)
    await app.soft_delete()
    await get_channel_layer().group_send(
        f"a/{app.id}", "force_reconnect", {"reason": "app_deleted"}
    )
    return {"detail": "App deleted"}


@applications_router.post("/cr")
async def request_code_registration(
    request: Request, del_code: Optional[str] = Query(None)
):
    code = await OneTimeSecurityCode.new(
        "new_app", ip_address=request.client.host
    )
    if del_code and await OneTimeSecurityCode.exists(del_code, "new_app"):
        await OneTimeSecurityCode.find({"_id": del_code}).delete()
    return {
        "code": code.id,
        "expires_at": code.expires_at.replace(tzinfo=timezone.utc),
        "ttl": OneTimeSecurityCode.DEFAULT_LIFETIME.total_seconds(),
    }


@applications_router.delete("/cr")
async def delete_request_code(code: str = Query(...)):
    instance = await OneTimeSecurityCode.get_valid_code("new_app", code)
    if instance:
        await instance.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class CRFinishRequest(AppBaseModel):
    name: str
    description: str
    display_name: str
    tags: list[str]


class CRFinishResponse(AppBaseModel):
    access_key: str
    id: PydanticObjectId


@applications_router.post("/cr", response_model=CRFinishResponse)
async def finish_code_registration(code: str, body: CRFinishRequest):
    code_inst = await OneTimeSecurityCode.get_valid_code("new_app", code)
    if code_inst is None:
        raise HTTPException(404, "code does not exist or expired")
    if not code_inst.confirmed:
        raise HTTPException(401, "code is not confirmed yet")
    app = Application(
        name=body.name,
        description=body.description,
        tags=body.tags,
        display_name=body.display_name,
    )
    await code_inst.save()
    await code_inst.delete()
    return {"access_key": app.access_key, "id": app.id}


def _detailed_application_task_view(task: ApplicationTask, app: Application):
    return {
        **task.dict(exclude={"app_id"}, by_alias=True),
        "app": app.dict(include={"name", "id", "display_name"}, by_alias=True),
    }


@applications_router.get("/defined-tasks/check-if-name-taken")
async def check_if_task_name_taken(name: str = Query(...)):
    return (
        await ApplicationTask.not_deleted()
        .find(ApplicationTask.name == name)
        .exists()
    )


@applications_router.get("/{app_ident}/defined-tasks")
async def get_application_tasks(
    app_ident: str, include_deleted: bool = Query(False)
):
    app = await _get_application(app_ident)
    return await _internal.get_application_tasks(
        app.id, include_deleted=include_deleted
    )


@applications_router.post("/{app_ident}/defined-tasks")
async def define_application_task(
    app_ident: str, body: _internal.DefineTask = Body(...)
):
    app = await _get_application(app_ident)
    task = await _internal.define_task(app, body)
    await _internal.notify_task_changed(task)
    return _detailed_application_task_view(task, app)
