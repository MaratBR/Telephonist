from typing import *

import fastapi
from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import Body, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

import server.internal.telephonist.events as events_internal
from server.internal.auth.dependencies import UserToken, Token, ResourceKey
from server.internal.channels.hub import ws_controller, Hub, bind_message, HubAuthenticationException
from server.internal.telephonist.utils import ChannelGroups
from server.models.auth import TokenModel
from server.models.common import Pagination, Identifier
from server.models.telephonist import Event, Application, EventSource, ApplicationHost
from server.utils.common import QueryDict

router = fastapi.APIRouter(tags=['events'], prefix='/events')


class EventsFilter(BaseModel):
    event_type: Optional[str]
    receiver: Optional[PydanticObjectId]


@router.get('/', dependencies=[UserToken()])
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
    related_task: Optional[Identifier]
    data: Optional[Any]
    on_behalf_of_app: Optional[PydanticObjectId]


@router.post('/publish', description='Publish event')
async def publish_event_endpoint(
        request: Request,
        body: PublishEventRequest = Body(...),
        user_token: Optional[TokenModel] = UserToken(required=False),
        rk: ResourceKey = ResourceKey.Depends('application', 'host')
):
    if user_token is None:
        if rk.resource_type == 'application':
            app = await Application.find_by_key(rk.resource_key)
            if app.app_host_id:
                raise HTTPException(401, 'this applications belongs to the application host')
        elif rk.resource_type == 'host':
            if body.on_behalf_of_app is None:
                raise HTTPException(422, 'on_behalf_of_app must be provided when publishing from a host')
            host = await ApplicationHost.find_by_key(rk.resource_key)
            app = await Application.get(body.on_behalf_of_app)
            if app is None or app.app_host_id != host.id:
                raise HTTPException(401, f'application {body.on_behalf_of_app} does not belong '
                                         f'to this host or does not exist')
        else:
            raise RuntimeError('unexpected type of resource')
        source_type = EventSource.APPLICATION

    else:
        source_type = EventSource.USER
        source_id = user_token.sub
    event = Event(
        source_id=source_id,
        source_type=source_type,
        event_type=body.name,
        data=body.data,
        publisher_ip=request.client.host,
        related_task_type=body.related_task
    )
    await event.save()
    await events_internal.publish_event(event)
    return {'details': 'Published'}


@ws_controller(router, '/app-report')
class AppReportHub(Hub):
    token: str = Token()
    _app: Application

    async def authenticate(self):
        self._app = await Application.find_by_token(self.token)
        if self._app is None:
            raise HubAuthenticationException('application key is invalid')

    async def on_connected(self):
        await self.websocket.close()

    class ListenConfigAll(BaseModel):
        category: Literal['all']

    class ListenConfig(BaseModel):
        category: Literal['name', 'task']
        parameter: str

    @bind_message('listen')
    async def on_listen_for_messages(self, listen_config: Optional[Union[ListenConfig, ListenConfigAll]]):
        if listen_config is None:
            groups = []
        elif isinstance(listen_config, self.ListenConfigAll):
            groups = [ChannelGroups.EVENTS]
        elif isinstance(listen_config, self.ListenConfig):
            if listen_config.category == 'name':
                groups = [ChannelGroups.event(listen_config.parameter)]
            elif listen_config.category == 'task':
                groups = [ChannelGroups.task_events(listen_config.parameter)]
            else:
                raise NotImplementedError()
        else:
            raise NotImplementedError()

        await self.connection.remove_all_groups()
        for g in groups:
            await self.connection.add_to_group(g)
        await self.send_message('subscription_updated', groups)

'''
@router.websocket('/events/app-report/1/{app_id}')
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
            'data': ev.data.json()
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
'''