from datetime import datetime, timedelta
from typing import *
from uuid import UUID

import fastapi
from beanie import PydanticObjectId
from fastapi import Body, Depends, HTTPException, Query, params
from pydantic import BaseModel

import server.internal.telephonist.application as _internal
from server.internal.auth.dependencies import AccessToken
from server.internal.auth.token import UserTokenModel
from server.internal.telephonist import realtime
from server.internal.telephonist.utils import Errors, require_model_with_id
from server.models.common import IdProjection, Pagination, PaginationResult
from server.models.telephonist import (
    Application,
    ApplicationTask,
    ApplicationView,
    AppLog,
    ConnectionInfo,
    OneTimeSecurityCode,
)

_APPLICATION_NOT_FOUND = "Application not found"
TOKEN: Union[params.Depends, UserTokenModel] = AccessToken()


async def _get_application(app_id: PydanticObjectId):
    return Errors.raise404_if_none(
        await Application.get_not_deleted(app_id), f"Application with id={app_id} not found"
    )


applications_router = fastapi.APIRouter(prefix="/applications")


class ApplicationsPagination(Pagination):
    ordered_by_options = {"name", "_id"}


@applications_router.get(
    "", responses={200: {"model": PaginationResult[ApplicationView]}}, dependencies=[AccessToken()]
)
async def get_applications(
    args: ApplicationsPagination = Depends(),
) -> PaginationResult[ApplicationView]:
    return await args.paginate(Application, ApplicationView)


@applications_router.post("", status_code=201, responses={201: {"model": IdProjection}})
async def create_application(_=AccessToken(), body: _internal.CreateApplication = Body(...)):
    app = await _internal.create_new_application(body)
    return ApplicationView(**app.dict())


@applications_router.get("/check-if-name-taken")
async def check_if_application_name_taken(name: str = Query(...)):
    return await Application.not_deleted().find(Application.name == name).exists()


@applications_router.get("/{app_id}")
async def get_application(app_id: PydanticObjectId):
    app = await _get_application(app_id)
    connections = await ConnectionInfo.find(ConnectionInfo.app_id == app.id).to_list()
    return {"app": app, "connections": connections}


@applications_router.get("/name/{app_name}")
async def find_application_by_name(app_name: str):
    return Errors.raise404_if_none(
        await Application.find_one(Application.name == app_name).project(ApplicationView),
        f"Application with name={app_name} not found",
    )


@applications_router.patch("/{app_id}", dependencies=[AccessToken()])
async def update_application(
    app_id: PydanticObjectId, update: _internal.ApplicationUpdate = Body(...)
):
    app = await _get_application(app_id)
    app.display_name = app.display_name if update.display_name is None else update.display_name
    app.description = app.description if update.description is None else update.description
    app.tags = app.tags if update.tags is None else update.tags
    if update.disabled is not None and update.disabled != app.disabled:
        if update.disabled:
            await realtime.on_application_disabled(app.id, update.disabled)
        app.disabled = update.disabled
    await app.save_changes()
    return ApplicationView(**app.dict(by_alias=True))


@applications_router.get("/{app_id}/logs")
async def get_app_logs(
    app_id: PydanticObjectId, before: Optional[datetime] = None, _=AccessToken()
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


class CRRequest(BaseModel):
    client_name: str


@applications_router.post("/cr/start")
async def request_code_registration(body: CRRequest = Body(...)):
    code = await OneTimeSecurityCode.new("new_app_code", body.client_name)
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
    code.expires_at = datetime.utcnow() + timedelta(days=10)
    await code.save()
    return {"detail": "Code confirmed"}


class CRFinishRequest(BaseModel):
    name: str
    description: str


class CRFinishResponse(BaseModel):
    access_key: str
    id: PydanticObjectId


@applications_router.post("/code-register/finish/{code}", response_model=CRFinishResponse)
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


@applications_router.get("/defined-tasks/check-if-name-taken")
async def check_if_task_name_taken(name: str = Query(...)):
    return await ApplicationTask.not_deleted().find(ApplicationTask.name == name).exists()


@applications_router.get("/{app_id}/defined-tasks")
async def get_application_tasks(app_id: PydanticObjectId, include_deleted: bool = Query(False)):
    Errors.raise404_if_false(
        await Application.find({"_id": app_id}).exists(),
        message=f"Application with id={app_id} not found",
    )
    return await _internal.get_application_tasks(app_id, include_deleted=include_deleted)


@applications_router.post("/{app_id}/defined-tasks", dependencies=[AccessToken()])
async def define_new_application_task__user(
    app_id: PydanticObjectId, body: _internal.DefineTask = Body(...)
):
    app = await _get_application(app_id)
    return await _internal.define_application_task(app, body)


@applications_router.delete("/{app_id}/defined-tasks/{task_id}")
async def deactivate_task(app_id: PydanticObjectId, task_id: UUID):
    task = await _internal.get_application_task(app_id, task_id)
    await _internal.deactivate_application_task(task)
    return {"detail": f"Task {task_id} has been deactivated"}


@applications_router.patch("/{app_id}/defined-tasks/{task_id}")
async def update_task(
    app_id: PydanticObjectId, task_id: UUID, update: _internal.TaskUpdate = Body(...)
):
    task = await _internal.get_application_task(app_id, task_id)
    await _internal.apply_application_task_update(task, update)
    return task
