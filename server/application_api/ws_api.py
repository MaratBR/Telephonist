import inspect
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Optional

from beanie import PydanticObjectId
from beanie.odm.operators.find.comparison import In
from fastapi import APIRouter, Depends, Query

from server import VERSION
from server.application_api._utils import APPLICATION
from server.auth.services import TokenService
from server.common.channels import WSTicket, WSTicketModel
from server.common.channels.hub import (
    Hub,
    HubAuthenticationException,
    bind_message,
    ws_controller,
)
from server.common.models import AppBaseModel
from server.common.services.application import ApplicationService
from server.common.services.logs import LogRecord, LogsService
from server.common.services.sequence import SequenceService
from server.common.services.task import DefinedTask
from server.database import (
    Application,
    ApplicationTask,
    EventSequence,
    EventSequenceState,
)
from server.database.connection_info import (
    ApplicationClientInfo,
    ConnectionInfo,
)
from server.database.server import Server

ws_router = APIRouter(prefix="/ws", tags=["ws"])
logger = logging.getLogger("telephonist.application_api.ws")


@ws_router.post("/issue-ws-ticket")
async def issue_websocket_token(
    app=APPLICATION, token_service: TokenService = Depends()
):
    exp = datetime.now() + timedelta(minutes=2)
    return {
        "ticket": token_service.encode(
            WSTicketModel[Application](exp=exp, sub=app.id)
        ),
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
    logs: List[LogRecord]


@ws_controller(ws_router, "/report")
class AppReportHub(Hub):
    ticket: WSTicketModel[Application] = WSTicket(Application)
    same_ip: Optional[str] = Query(None)
    application_service: ApplicationService = Depends()
    sequence_service: SequenceService = Depends()
    logs_service: LogsService = Depends()
    _app_id: PydanticObjectId
    _connection_info: Optional[ConnectionInfo] = None
    _connection_info_expire: datetime = datetime.min
    _settings_allowed: bool
    _app: Application

    def __init__(self):
        super(AppReportHub, self).__init__()
        self._subscriptions = set()
        self._ready = False

    async def authenticate(self):
        if self.ticket is None:
            raise HubAuthenticationException("resource key is missing")
        app = await Application.get(self.ticket.sub)
        if app is None:
            raise HubAuthenticationException("application could not be found")
        self._app_id = app.id
        await self._get_application()

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
        self._app = await Application.get(self._app_id)
        assert self._app is not None, "Application is None"
        return self._app

    async def _fetch_connection(self):
        if self._connection_info is None:
            raise RuntimeError("self._connection_info is None")
        self._connection_info = await ConnectionInfo.get(
            self._connection_info.id
        )

    async def on_disconnected(self, exc: Exception = None):
        if self._connection_info is not None:
            self._connection_info = await ConnectionInfo.get(
                self._connection_info.id
            )
            if self._connection_info is None:
                return
            self._connection_info.is_connected = False
            self._connection_info.expires_at = datetime.utcnow() + timedelta(
                hours=12
            )
            self._connection_info.disconnected_at = datetime.utcnow()
            await self._connection_info.save_changes()
            await self.application_service.notify_connection_changed(
                self._connection_info
            )
            q = EventSequence.find(
                EventSequence.connection_id == self._connection_info.id,
                EventSequence.state == EventSequenceState.IN_PROGRESS,
            )
            await q.update(
                {
                    "$set": {
                        "state": EventSequenceState.FROZEN,
                        "state_updated_at": datetime.utcnow(),
                    }
                }
            )
            sequences = await q.to_list()
            for seq in sequences:
                await self.sequence_service.notify_sequence_changed(seq)

            await self.channel_layer.group_send(
                f"m/connections/{self._connection_info.id}", "updated"
            )

    @bind_message("hello")
    async def on_hello(self, message: HelloMessage):
        if self._ready:
            await self.send_error(
                "You cannot introduce yourself twice, dummy!"
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
        await self.send_message(
            "greetings",
            {
                "connections_total": await ConnectionInfo.find(
                    ConnectionInfo.is_connected == True,  # noqa
                    ConnectionInfo.app_id == self._app_id,
                ).count(),
            },
        )
        await self.channel_layer.group_send(
            f"m/connections/{self._connection_info.id}", "updated"
        )
        await self.synchronize_tasks()

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)
        await self.check_orphans()

    @bind_message("abandon")
    @_if_ready_only
    async def abandon_sequences(self, sequences: list[PydanticObjectId]):
        q = EventSequence.find(
            EventSequence.connection_id == self._connection_info,
            EventSequence.state == EventSequenceState.FROZEN,
            In("_id", sequences),
        )
        sequences = await q.to_list()
        if len(sequences) > 0:
            await q.update(
                {"$set": {"state": EventSequenceState.ORPHANED.name}}
            )
            for seq in sequences:
                await self.sequence_service.notify_sequence_changed(seq)

    @bind_message("check_orphans")
    @_if_ready_only
    async def check_orphans(self):
        if self._connection_info is None:
            raise RuntimeError(
                "connection info is not set yet for some reason, bug?"
            )
        frozen = await EventSequence.find(
            EventSequence.connection_id == self._connection_info,
            EventSequence.state == EventSequenceState.FROZEN,
        ).to_list()
        if len(frozen) > 0:
            await self.send_message(
                "detected_orphans", {"ids": [str(s.id) for s in frozen]}
            )

    @bind_message("set_subscriptions")
    @_if_ready_only
    async def set_subscriptions(self, subscriptions: List[str]):
        for s in self._subscriptions:
            logger.debug(
                f"application {self._app.name} ({self._app.id}) unsubscribed"
                f" from event {s}"
            )
            await self.connection.remove_from_group(f"e/key/{s}")

        for s in subscriptions:
            logger.debug(
                f"application {self._app.name} ({self._app.id}) subscribed to"
                f" event {s}"
            )
            await self.connection.add_to_group(f"e/key/{s}")
        await self._connection_info.update(
            {"$set": {"event_subscriptions": subscriptions}},
            ignore_revision=True,
        )

    @bind_message("subscribe")
    @_if_ready_only
    async def subscribe(self, event_type: str):
        self._subscriptions.add(event_type)
        logger.debug(
            f"application {self._app.name} ({self._app.id}) subscribed to"
            f" event {event_type}"
        )
        await self.connection.add_to_group(f"e/key/{event_type}")
        await ConnectionInfo.add_subscription(
            self._connection_info.id, event_type
        )

    @bind_message("unsubscribe")
    @_if_ready_only
    async def unsubscribe(self, event_type: str):
        self._subscriptions.remove(event_type)
        logger.debug(
            f"application {self._app.name} ({self._app.id}) unsubscribed from"
            f" event {event_type}"
        )
        await self.connection.remove_from_group(f"e/key/{event_type}")
        await ConnectionInfo.remove_subscription(
            self._connection_info.id, event_type
        )

    @bind_message("synchronize")
    @_if_ready_only
    async def synchronize_tasks(self):
        tasks = (
            await ApplicationTask.not_deleted()
            .find(ApplicationTask.app_id == self.ticket.sub)
            .to_list()
        )
        await self.send_message(
            "tasks", [DefinedTask.from_db(t) for t in tasks]
        )

    @bind_message("send_log")
    @_if_ready_only
    async def send_log(self, log_message: LogMessage):
        models = await self.logs_service.send_logs(
            self.ticket.sub, log_message.sequence_id, log_message.logs
        )
        await self.send_message(
            "logs_sent", {"count": len(models), "last": models[-1].id}
        )
