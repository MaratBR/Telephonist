from typing import *

from beanie import PydanticObjectId
from fastapi import Body, HTTPException
from pydantic import BaseModel, Field

from server.auth.utils import UserToken
from server.common.models import Pagination, PaginationResult
from server.telephonist.models import Application
from ._router import router
from ..utils import raise404_if_none
from ...channels import broadcast


@router.get('/applications', responses={200: {"model": PaginationResult[Application.PublicView]}})
async def get_applications(
        _=UserToken(),
        args: Pagination = Pagination.from_choices(['name', 'id']),
) -> PaginationResult[Application.PublicView]:
    return await args.paginate(Application, Application.PublicView)


class CreateApplication(BaseModel):
    name: str
    description: Optional[str] = Field(max_length=400)
    tags: Optional[List[str]]
    disabled: bool = False


@router.post('/applications')
async def create_application(_=UserToken(), body: CreateApplication = Body(...)):
    app = Application(
        name=body.name, description=body.description, disabled=body.disabled,
        tags=[] if body.tags is None else list(set(body.tags)),
    )
    await app.save()


class GetApplicationTokenRequest(BaseModel):
    token: str


@router.post('/applications/token')
async def get_application_token(token: GetApplicationTokenRequest):
    app = await Application.find_one(Application.access_token == token.token)
    if app:
        return {
            'access_token': app.create_token().encode(),
            'token_type': 'bearer'
        }
    raise HTTPException(404, 'Application with given token not found')


@router.get('/applications/{app_id}')
async def get_application(
        app_id: PydanticObjectId
):
    return raise404_if_none(
        await Application.find_one({'_id': app_id}).project(Application.PublicView),
        'Application not found'
    )


class UpdateApplication(BaseModel):
    name: Optional[str]
    description: Optional[str] = Field(max_length=400)
    disabled: Optional[bool]
    receive_offline: Optional[bool]


@router.get('/applications/name/{app_name}')
async def get_application(
        app_name: str
):
    return raise404_if_none(
        await Application.find_one(Application.name == app_name).project(Application.PublicView),
        'Application not found'
    )


@router.patch('/application/{app_id}')
async def update_application(app_id: PydanticObjectId, body: UpdateApplication = Body(...)):
    app = raise404_if_none(await Application.get(app_id))
    app.name = body.name or app.display_name
    app.description = body.description or app.description

    if body.receive_offline is not None:
        app.settings.receive_offline = body.receive_offline

    await app.save_changes()

    if body.disabled is not None and body.disabled != app.disabled:
        if body.disabled:
            await broadcast.publish(f'app_disabled:{app_id}')
        app.disabled = body.disabled

    return app
