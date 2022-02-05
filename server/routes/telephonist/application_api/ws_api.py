import inspect
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Optional

from beanie import PydanticObjectId
from beanie.odm.operators.find.comparison import In
from fastapi import APIRouter, Query

import server.internal.telephonist as _internal
from server import VERSION
from server.internal.channels import WSTicket, WSTicketModel
from server.internal.channels.hub import (
    Hub,
    HubAuthenticationException,
    bind_message,
    ws_controller,
)
from server.internal.telephonist.utils import CG
from server.models.telephonist import (
    Application,
    ConnectionInfo,
    EventSequence,
    EventSequenceState,
    Server,
)
from server.routes.telephonist.application_api._utils import APPLICATION

ws_router = APIRouter(prefix="/ws", tags=["ws"])


@ws_router.post("/issue-ws-ticket")
async def issue_websocket_token(app=APPLICATION):
    exp = datetime.now() + timedelta(minutes=2)
    return {"ticket": WSTicketModel[Application](exp=exp, sub=app.id).encode(), "exp": exp}


class HelloMessage(_internal.ApplicationClientInfo):
    subscriptions: Optional[List[str]]
    pid: Optional[int]


def _if_ready_only(f):
    assert inspect.iscoroutinefunction(f)

    @wraps(f)
    async def wrapper(self, *args, **kwargs):
        if not self._ready:
            await self.send_error('You have to send "hello" message first')
            return
        return await f(*args, **kwargs)

    return wrapper


@ws_controller(ws_router, "/")
class AppReportHub(Hub):
    ticket: WSTicketModel[Application] = WSTicket(Application)
    same_ip: Optional[str] = Query(None)
    _app_id: PydanticObjectId
    _connection_info: Optional[ConnectionInfo] = None
    _connection_info_expire: datetime = datetime.min
    _settings_allowed: bool

    def __init__(self):
        super(AppReportHub, self).__init__()
        self._ready = False

    async def _refresh_bound_sequences(self):
        sequences = await EventSequence.find(
            In("_id", self._connection_info.bound_sequences),
            EventSequence.app_id == self._app_id,
            EventSequence.state == EventSequenceState.IN_PROGRESS,
        ).to_list()

    async def authenticate(self):
        if self.ticket is None:
            raise HubAuthenticationException("resource key is missing")
        app = await Application.get(self.ticket.sub)
        if app is None:
            raise HubAuthenticationException("application could not be found")
        self._app_id = app.id
        self._settings_allowed = app.are_settings_allowed

    async def on_connected(self):
        await self.send_message(
            "introduction",
            {
                "server_version": VERSION,
                "authentication": "ok",
                "app_id": self._app_id,
            },
        )

    async def _get_application(self):
        app = await Application.get(self._app_id)
        assert app is not None, "Application is None"
        return app

    async def _send_connection(self):
        await self.channel_layer.group_send(
            CG.entry("application", self._app_id),
            "entry_update",
            {
                "entry_name": "connection_info",
                "id": self._connection_info.id,
                "entry": self._connection_info,
                "proto_version": 1,
            },
        )

    async def on_disconnected(self, exc: Exception = None):
        if self._connection_info is not None:
            await self._refresh_bound_sequences()
            self._connection_info.bound_sequences = list(self._bound_sequences)
            await _internal.set_sequences_frozen(
                self._app_id, self._connection_info.bound_sequences, True
            )
            await _internal.on_connection_disconnected(self._connection_info)

    @bind_message("hello")
    async def on_hello(self, message: HelloMessage):
        if self._ready:
            await self.send_error("you cannot introduce yourself twice, dummy!")
            return
        self._ready = True
        self._connection_info = await _internal.get_or_create_connection(
            self._app_id, message, self.websocket.client.host
        )
        await Server.report_server(
            self.websocket.client, None if message.os_info == "" else message.os_info
        )
        await self._send_connection()
        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)
        await self.connection.add_to_group(CG.app(self._app_id))
        await EventSequence.find(
            EventSequence.frozen == True,
            EventSequence.connection_id == self._connection_info.id,
            EventSequence.state == EventSequenceState.IN_PROGRESS,
        ).update({"$set": {"frozen": False}})
        await self.send_message(
            "greetings",
            {
                "connections_total": await ConnectionInfo.find(
                    ConnectionInfo.is_connected == True,  # noqa
                    ConnectionInfo.app_id == self._app_id,
                ).count(),
            },
        )

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)

    @bind_message("set_subscriptions")
    @_if_ready_only
    async def set_subscriptions(self, subscriptions: List[str]):
        await self._fetch_connection()
        await self._connection_info.update({"event_subscriptions": subscriptions})
        await self._send_connection()

    @bind_message("subscribe")
    @_if_ready_only
    async def subscribe(self, event_type: str):
        await self.connection.add_to_group(CG.events(event_type=event_type))
        await _internal.add_connection_subscription(self._connection_info.id, [event_type])
        await self._send_connection()

    @bind_message("unsubscribe")
    @_if_ready_only
    async def unsubscribe(self, event_type: str):
        await self.connection.remove_from_group(CG.events(event_type=event_type))
        await _internal.remote_connection_subscription(self._connection_info.id, [event_type])
        await self._send_connection()

    @bind_message("synchronize")
    @_if_ready_only
    async def synchronize_tasks(self, tasks: List[_internal.DefinedTask]):
        await self.send_message(
            "tasks", await _internal.sync_defined_tasks(await self._get_application(), tasks)
        )
