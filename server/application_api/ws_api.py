import inspect
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Query

import server.common.internal as _internal
from server import VERSION
from server.application_api._utils import APPLICATION
from server.common.channels import WSTicket, WSTicketModel
from server.common.channels.hub import (
    Hub,
    HubAuthenticationException,
    bind_message,
    ws_controller,
)
from server.common.internal.utils import CG
from server.common.models import AppBaseModel
from server.database import Application, ApplicationTask
from server.database.connection_info import ApplicationClientInfo, ConnectionInfo
from server.database.server import Server
from server.ws_root_router import ws_root_router

ws_router = APIRouter(prefix="/ws", tags=["ws"])


@ws_router.post("/issue-ws-ticket")
async def issue_websocket_token(app=APPLICATION):
    exp = datetime.now() + timedelta(minutes=2)
    return {
        "ticket": WSTicketModel[Application](exp=exp, sub=app.id).encode(),
        "exp": exp,
    }


class HelloMessage(ApplicationClientInfo):
    subscriptions: Optional[List[str]]
    pid: Optional[int]


def _if_ready_only(f):
    assert inspect.iscoroutinefunction(f)

    @wraps(f)
    async def wrapper(self, *args, **kwargs):
        if not self._ready:
            await self.send_error('You have to send "hello" message first')
            return
        return await f(self, *args, **kwargs)

    return wrapper


class LogMessage(AppBaseModel):
    sequence_id: Optional[PydanticObjectId]
    logs: List[_internal.LogRecord]


# unless https://github.com/tiangolo/fastapi/pull/2640 gets merged, we're stuck with this workaround
@ws_controller(ws_root_router, "/_ws/application/report")
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

    async def authenticate(self):
        if self.ticket is None:
            raise HubAuthenticationException("resource key is missing")
        app = await Application.get(self.ticket.sub)
        if app is None:
            raise HubAuthenticationException("application could not be found")
        self._app_id = app.id

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

    async def on_disconnected(self, exc: Exception = None):
        if self._connection_info is not None:
            self._connection_info = await ConnectionInfo.get(
                self._connection_info.id
            )
            self._connection_info.is_connected = False
            self._connection_info.expires_at = datetime.utcnow() + timedelta(
                hours=12
            )
            self._connection_info.disconnected_at = datetime.utcnow()
            await self._connection_info.save_changes()
            await _internal.notify_connection_changed(self._connection_info)

    @bind_message("hello")
    async def on_hello(self, message: HelloMessage):
        if self._ready:
            await self.send_error(
                "you cannot introduce yourself twice, dummy!"
            )
            return
        self._ready = True
        self._connection_info = await ConnectionInfo.find_or_create(
            self._app_id, message, self.websocket.client.host
        )
        await Server.report_server(
            self.websocket.client,
            None if message.os_info == "" else message.os_info,
        )
        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)
        await self.connection.add_to_group(f"a/{self._app_id}")
        # TODO find and unfreeze all frozen tasks
        # TODO #2 ask the client regarding those sequences
        await self.send_message(
            "greetings",
            {
                "connections_total": await ConnectionInfo.find(
                    ConnectionInfo.is_connected == True,  # noqa
                    ConnectionInfo.app_id == self._app_id,
                ).count(),
            },
        )
        await self.synchronize_tasks()

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)

    @bind_message("set_subscriptions")
    @_if_ready_only
    async def set_subscriptions(self, subscriptions: List[str]):
        await self._fetch_connection()
        await self._connection_info.update(
            {"event_subscriptions": subscriptions}
        )
        await self._send_connection()

    @bind_message("subscribe")
    @_if_ready_only
    async def subscribe(self, event_type: str):
        await self.connection.add_to_group("")
        await ConnectionInfo.add_subscription(
            self._connection_info.id, event_type
        )

    @bind_message("unsubscribe")
    @_if_ready_only
    async def unsubscribe(self, event_type: str):
        await self.connection.remove_from_group(
            CG.events(event_type=event_type)
        )
        await ConnectionInfo.remove_subscription(
            self._connection_info.id, event_type
        )

    @bind_message("synchronize")
    @_if_ready_only
    async def synchronize_tasks(self):
        tasks = await ApplicationTask.not_deleted().find(ApplicationTask.app_id == self.ticket.sub).to_list()
        tasks = await ApplicationTask.find(ApplicationTask.app_id == self.ticket.sub).to_list()

        await self.send_message("tasks", [_internal.DefinedTask.from_db(t) for t in tasks])

    @bind_message("send_log")
    @_if_ready_only
    async def send_log(self, log_message: LogMessage):
        models = await _internal.send_logs(
            self.ticket.sub, log_message.sequence_id, log_message.logs
        )
        await self.send_message(
            "logs_sent", {"count": len(models), "last": models[-1].id}
        )
