from datetime import datetime, timedelta
from typing import *

import fastapi
from beanie import PydanticObjectId
from fastapi import Body, HTTPException
from pydantic import BaseModel, Field
from starlette import status

from server.internal.auth.dependencies import UserToken
from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import Errors
from server.models.common import PaginationResult, Pagination, IdProjection
from server.models.telephonist import Application, AppLog

_APPLICATION_NOT_FOUND = 'Application not not found'
_APPLICATION_HOSTED = 'Application is hosted'
router = fastapi.APIRouter(prefix='/applications', tags=['applications'])


class CreateApplication(BaseModel):
    name: str
    description: Optional[str] = Field(max_length=400)
    tags: Optional[List[str]]
    disabled: bool = False


class GetApplicationTokenRequest(BaseModel):
    token: str


class UpdateApplication(BaseModel):
    name: Optional[str]
    description: Optional[str] = Field(max_length=400)
    disabled: Optional[bool]
    receive_offline: Optional[bool]


@router.get('', responses={200: {"model": PaginationResult[Application.ApplicationView]}})
async def get_applications(
        _=UserToken(),
        args: Pagination = Pagination.from_choices(['name', 'id']),
) -> PaginationResult[Application.ApplicationView]:
    return await args.paginate(Application, Application.ApplicationView)


@router.post('', status_code=201, responses={201: {"model": IdProjection}})
async def create_application(_=UserToken(), body: CreateApplication = Body(...)):
    if await Application.find(Application.name == body.name).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, 'Application with given name already exists')
    app = Application(
        name=body.name, description=body.description, disabled=body.disabled,
        tags=[] if body.tags is None else list(set(body.tags)),
    )
    await app.save()
    return IdProjection(id=app.id)


@router.get('/{app_id}')
async def get_application(
        app_id: PydanticObjectId
):
    return Errors.raise404_if_none(
        await Application.find_one({'_id': app_id}).project(Application.ApplicationView),
        _APPLICATION_NOT_FOUND
    )


@router.get('/name/{app_name}')
async def get_application(
        app_name: str
):
    return Errors.raise404_if_none(
        await Application.find_one(Application.name == app_name).project(Application.ApplicationView),
        _APPLICATION_NOT_FOUND
    )


@router.patch('/{app_id}')
async def update_application(
        app_id: PydanticObjectId,
        body: UpdateApplication = Body(...),
        user_token=UserToken(),
):
    app = Errors.raise404_if_none(await Application.get(app_id), _APPLICATION_NOT_FOUND)
    if app.is_hosted:
        raise HTTPException(status.HTTP_409_CONFLICT, _APPLICATION_HOSTED)
    app.name = body.name or app.display_name
    app.description = body.description or app.description

    if body.receive_offline is not None:
        app.settings.receive_offline = body.receive_offline

    await app.save_changes()

    if body.disabled is not None and body.disabled != app.disabled:
        if body.disabled:
            await get_channel_layer().group_send(f'app{app.id}', 'app_disabled', None)
        app.disabled = body.disabled

    return app


@router.get('/{app_id}/logs',)
async def get_app_logs(
        app_id: PydanticObjectId,
        before: Optional[datetime] = None,
        _=UserToken()
):
    Errors.raise404_if_false(await Application.find({'_id': app_id}).exists())
    if before is None:
        logs = AppLog.find()
    else:
        logs = AppLog.find_before(before)
    logs = await logs.limit(100)
    return {
        'before': before,
        'logs': logs
    }


@router.post('/token')
async def get_application_token(token: GetApplicationTokenRequest):
    app = await Application.find_one(Application.token == token.token)
    if app:
        return {
            'access_token': app.create_token(lifetime=timedelta(hours=1)).encode(),
            'token_type': 'bearer'
        }
    raise HTTPException(404, _APPLICATION_NOT_FOUND)