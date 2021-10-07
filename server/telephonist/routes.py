import asyncio
from typing import Optional, Any

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel
from starlette import status
from starlette.requests import Request
from starlette.websockets import WebSocket

from server.auth.models import User
from server.auth.utils import require_bearer, CurrentUser
from server.channels import BroadcastEvent, wscode
from server.channels.helper import ChannelHelper
from server.common.models import PaginationWithOrdering
from server.telephonist import utils
from server.telephonist.models import Application, EventMessage, ConnectionInfo

router = APIRouter()


@router.get('/applications')
async def get_applications(
        args: PaginationWithOrdering = PaginationWithOrdering.from_choices(['name', 'created_at']),
):
    p = await args.paginate(Application)
    return p


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


class PublishEventRequest(BaseModel):
    name: str
    data: Optional[Any]


@router.post('/events/publish')
async def publish_event(
        request: Request,
        event_data: PublishEventRequest = Body(...),
        user: Optional[User] = CurrentUser(required=False),
        app_token: Optional[str] = Depends(require_bearer)
):
    if user is None:
        source = await Application.get_or_none(access_token=app_token)
        if source is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, 'Application not found')
    else:
        source = user
    await utils.publish_event(
        event_data.name,
        source,
        request.client.host,
        event_data.data,
    )
    return {'details': 'Published'}


@router.get('/applications/{app_id}')
async def get_application(
        app_id: PydanticObjectId
):
    app = await Application.get(app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f'Application _id="{app_id}" not found')
    return app


@router.get('/applications/name/{app_name}')
async def get_application(
        app_name: str
):
    app = await Application.find_one(Application.name == app_name)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f'Application "{app_name}" not found')
    return app


@router.post('/app-report/{app_id}/startup')
async def post_report(app_id: PydanticObjectId):
    application = await Application.get(app_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Application not found')


class AppInitialMessage(BaseModel):
    pass


class AppRaiseEventMessage(BaseModel):
    event_name: str
    data: Any


@router.websocket('/app-report/{app_id}')
async def app_report(
        app_id: Optional[str],
        ws: WebSocket,
        helper: ChannelHelper = Depends()
):
    await ws.accept()

    if app_id is None:
        await helper.send_error('App id was not provided')
        await ws.close(wscode.WSC_INVALID)
        return
    try:
        app_id = PydanticObjectId(app_id)
    except InvalidId:
        await helper.send('Invalid app id')
        await ws.close(wscode.WSC_INVALID)
        return

    app = await Application.get(app_id)
    if app is None:
        await helper.send('Application not found')
        await ws.close(wscode.WSC_NOT_FOUND)
        return

    await helper.send_message('hello')

    if app.has_connection:
        await helper.send_error('Another software is already connected to the server with this application key')

    connection_info = ConnectionInfo.from_websocket(ws)
    app.connection_info.append(connection_info)
    await app.save()

    got_initial = True  # ignore initial for now

    @helper.error
    async def on_error(exc: Exception):
        print('got error', exc)

    async def event(ev: BroadcastEvent):
        telephonist_event: EventMessage = ev.data
        await helper.send({
            'type': 'event',
            'message': telephonist_event.json()
        })

    await asyncio.gather(*(
        helper.subscribe('telephonist.events:' + sub.channel, event)
        for sub in app.event_subscriptions
    ))

    await helper.send_message('subscribed', [sub.channel for sub in app.event_subscriptions])

    @helper.message
    async def handle_message(msg_type: str, data: Any):
        nonlocal got_initial

        if msg_type == 'initial':
            message = AppInitialMessage(**data)
            got_initial = True
            # TODO handle initial message
        elif not got_initial:
            return  # no-op
        elif msg_type == 'update':
            pass
        elif msg_type == 'sub':
            if isinstance(data, str):
                await helper.subscribe('telephonist.events:' + data, event)
                await app.add_subscription(data)
                await helper.send_message('subscribed', data)
        elif msg_type == 'unsub':
            if isinstance(data, str):
                await helper.unsubscribe('telephonist.events:' + data)
                await app.remove_subscription(data)
                await helper.send_message('unsubscribed', data)

    await helper.start()

    app.connection_info.remove(connection_info)
    await app.save()
