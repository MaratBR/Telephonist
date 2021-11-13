from http.client import HTTPException
from typing import *

from beanie import PydanticObjectId
from beanie.operators import In
from bson.errors import InvalidId
from fastapi import Body, Depends
from pydantic import BaseModel
from starlette.requests import Request
from starlette.websockets import WebSocket

from server.auth.models import User, TokenModel
from server.auth.utils import TokenDependency, UserToken
from server.channels import ChannelHelper, wscode, BroadcastEvent
from server.common.models import Pagination
from server.common.utils import QueryDict
from server.telephonist.models import Application, ConnectionInfo, EventMessage, Event
from server.telephonist.utils import InternalChannels
from ._router import router
from .. import utils
from ...channels.controller import ChannelController, message_handler


class EventsFilter(BaseModel):
    event_type: Optional[str]
    receiver: Optional[PydanticObjectId]


@router.get('/events', dependencies=[UserToken()])
async def get_events(
        pagination: Pagination = Pagination.from_choices(['_id', 'event_type']),
        filter_data=QueryDict(EventsFilter)
):
    find = []

    if filter_data.event_type:
        find.append(Event.event_type == filter_data.event_type)
    if filter_data.receiver:
        find.append(In(Event.receivers, filter_data.receiver))
    return await pagination.paginate(Event, filter_condition=find)


class PublishEventRequest(BaseModel):
    name: str
    data: Optional[Any]


@router.post('/events/publish')
async def publish_event(
        request: Request,
        event_data: PublishEventRequest = Body(...),
        token: TokenModel = TokenDependency(subject={User, Application}),
):
    source = await token.sub.type.get(token.sub.oid)
    await utils.publish_event(
        event_data.name,
        source,
        request.client.host,
        event_data.data,
    )
    return {'details': 'Published'}


@router.post('/app-report/{app_id}/startup')
async def post_report(app_id: PydanticObjectId):
    application = await Application.get(app_id)
    if application is None:
        raise HTTPException(404, 'Application not found')


class AppInitialMessage(BaseModel):
    pass


class AppRaiseEventMessage(BaseModel):
    event_name: str
    data: Any


class AppReportController(ChannelController):
    @message_handler('initial')
    async def on_initial(self, _msg):
        pass


@router.websocket('/events/app-report/{app_id}')
async def app_report(
        app_id: Optional[str],
        ws: WebSocket,
        helper: ChannelHelper = Depends()
):
    await helper.accept()

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
    await app.save_changes()

    got_initial = True  # ignore initial for now

    @helper.error
    async def on_error(exc: Exception):
        print('got error', exc)

    @helper.channel(InternalChannels.app_events(app.id))
    async def event(ev: BroadcastEvent[EventMessage]):
        await helper.send_json({
            'type': 'event',
            'message': ev.data.json()
        })

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
                await helper.subscribe('events:' + data, event)
                await app.add_subscription(data)
                await helper.send_message('subscribed', data)
        elif msg_type == 'unsub':
            if isinstance(data, str):
                await helper.unsubscribe('events:' + data)
                await app.remove_subscription(data)
                await helper.send_message('unsubscribed', data)

    await helper.start()

    app.connection_info.remove(connection_info)
    await app.save_changes()


@router.websocket('/events/all')
async def all_events(
        _=UserToken(),
        helper: ChannelHelper = Depends(),
):
    @helper.channel(InternalChannels.EVENTS)
    async def on_event(event):
        await helper.send_message('event', event.data)

    await helper.start()


@router.websocket('/events/app/{app_id}')
async def app_events(
        app_id: PydanticObjectId,
        token: Optional[TokenModel] = UserToken(required=False),
        helper: ChannelHelper = Depends(),
):
    await helper.accept()
    if token is None:
        await helper.close(wscode.WSC_UNAUTHORIZED)
    if not await Application.find({'_id': app_id}).exists():
        await helper.close(wscode.WSC_NOT_FOUND, 'application not found')

    @helper.channel(InternalChannels.app_events(app_id))
    async def on_event(event: BroadcastEvent[EventMessage]):
        await helper.send_message('event', event.data)

    await helper.start()