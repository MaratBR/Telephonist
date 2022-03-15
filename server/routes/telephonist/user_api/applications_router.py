from datetime import datetime, timedelta
from typing import List, Optional, Union

import fastapi
from beanie import PydanticObjectId
from beanie.odm.enums import SortDirection
from bson.errors import InvalidId
from fastapi import Body, Depends, HTTPException, Query
from starlette.requests import Request

import server.internal.telephonist.application as _internal
from server.internal.telephonist.utils import Errors, require_model_with_id
from server.models.common import (
    AppBaseModel,
    Identifier,
    IdProjection,
    Pagination,
    PaginationResult,
)
from server.models.telephonist import (
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


async def _get_application(
    app_id_or_name: Union[PydanticObjectId, Identifier]
):
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
    try:
        app_id_or_name = PydanticObjectId(app_id_or_name)
    except InvalidId:
        pass
    app = await _get_application(app_id_or_name)
    connections = await ConnectionInfo.find(
        ConnectionInfo.app_id == app.id
    ).to_list()
    tasks = (
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
    return {
        "app": app,
        "connections": connections,
        "tasks": tasks,
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


@applications_router.get("/{app_id}/logs")
async def get_app_logs(
    app_id: PydanticObjectId,
    before: Optional[datetime] = None,
):
    await require_model_with_id(
        Application, app_id, message=f"Application with id={app_id} not found"
    )
    if before is None:
        logs = AppLog.find()
    else:
        logs = AppLog.find_before(before)
    logs = await logs.limit(100).to_list()
    return {"before": before, "logs": logs}


class CRRequest(AppBaseModel):
    client_name: str


@applications_router.post("/cr/start")
async def request_code_registration(
    request: Request, body: CRRequest = Body(...)
):
    code = await OneTimeSecurityCode.new(
        "new_app_code", body.client_name, ip_address=request.client.host
    )
    return {
        "code": code.id,
        "expires_at": code.expires_at,
        "ttl": OneTimeSecurityCode.DEFAULT_LIFETIME.total_seconds(),
    }


@applications_router.post("/cr/confirm")
async def confirm_code_registration(code: str = Query(...)):
    code = await OneTimeSecurityCode.get_valid_code("new_app_code", code)
    if code is None:
        raise HTTPException(404, "code does not exist or expired")
    code.confirmed = True
    code.expires_at = datetime.now() + timedelta(days=10)
    await code.save()
    return {"detail": "Code confirmed"}


class CRFinishRequest(AppBaseModel):
    name: str
    description: str


class CRFinishResponse(AppBaseModel):
    access_key: str
    id: PydanticObjectId


@applications_router.post(
    "/code-register/finish/{code}", response_model=CRFinishResponse
)
async def finish_code_registration(code: str, body: CRFinishRequest):
    code_inst = await OneTimeSecurityCode.get_valid_code("new_app_code", code)
    if code_inst is None:
        raise HTTPException(404, "code does not exist or expired")
    if not code_inst.confirmed:
        raise HTTPException(401, "code is not confirmed yet")
    app = Application(name=body.name, description=body.description)
    await code_inst.save()
    await code_inst.delete()
    return {"access_key": app.access_key, "id": app.id}


def _detailed_application_task_view(task: ApplicationTask, app: Application):
    return {
        **task.dict(exclude={"app_id", "app_name"}, by_alias=True),
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
    task = await _internal.define_application_task(app, body)
    return _detailed_application_task_view(task, app)


@applications_router.get("/{app_id_or_name}/sequences/{sequence_id}")
async def get_sequence(app_id_or_name: str, sequence_id: PydanticObjectId):
    try:
        app_id_or_name = PydanticObjectId(app_id_or_name)
    except InvalidId:
        pass
    app = await _get_application(app_id_or_name)
    sequence = await EventSequence.find_one(
        EventSequence.id == sequence_id, EventSequence.app_id == app.id
    )
    Errors.raise404_if_none(sequence)
    logs = (
        await AppLog.find(AppLog.sequence_id == sequence.id)
        .sort(("created_at", SortDirection.DESCENDING))
        .limit(3000)
        .to_list()
    )
    return {
        **sequence.dict(by_alias=True, exclude={"app_id"}),
        "app": app.dict(by_alias=True, include={"id", "name", "display_name"}),
        "logs": [
            {
                "t": log.created_at,
                "severity": log.severity,
                "body": log.body,
                "_id": log.id,
            }
            for log in logs
        ],
    }
