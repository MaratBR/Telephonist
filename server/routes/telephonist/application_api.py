import inspect
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Body, Depends, HTTPException, Query, params
from starlette.requests import Request

import server.internal.telephonist as _internal
from server import VERSION
from server.internal.auth.schema import require_bearer
from server.internal.channels import Hub, WSTicket, WSTicketModel
from server.internal.channels.hub import (
    HubAuthenticationException,
    bind_message,
    ws_controller,
)
from server.internal.telephonist.utils import CG
from server.models.telephonist import (
    Application,
    ApplicationTask,
    ConnectionInfo,
    Server,
)


async def _get_application_from_key(token: str = Depends(require_bearer)):
    app = await Application.find_by_key(token)
    if app is None:
        raise HTTPException(401, "Could not identify the application using provided access key")
    return app


APPLICATION: Union[Application, params.Depends] = Depends(_get_application_from_key)

application_api_router = APIRouter(
    prefix="/application-api", tags=["application-api"], dependencies=[APPLICATION]
)


@application_api_router.get("/self")
async def get_self(app=APPLICATION):
    return app


@application_api_router.get("/defined-tasks")
async def get_tasks(app=APPLICATION):
    tasks = await ApplicationTask.not_deleted().find(ApplicationTask.app_id == app.id).to_list()
    return tasks


@application_api_router.post("/defined-tasks")
async def define_app_task(app=APPLICATION, body: _internal.DefineTask = Body(...)):
    task = _internal.define_application_task(app, body)
    return task


@application_api_router.post("/defined-tasks/check")
async def find_defined_tasks(names: List[str] = Body(...), app=APPLICATION):
    tasks = await ApplicationTask.not_deleted().find(In("name", names)).to_list()
    taken = []
    belong_to_self = []
    for task in tasks:
        if task.app_id != app.id:
            taken.append(task.name)
        else:
            belong_to_self.append(task.name)

    return {
        "taken": taken,
        "belong_to_self": belong_to_self,
        "free": [t for t in names if t not in taken and t not in belong_to_self],
    }


@application_api_router.patch("/defined-tasks/{task_id}")
async def update_app_task(
    task_id: PydanticObjectId, app=APPLICATION, update: _internal.TaskUpdate = Body(...)
):
    task = await _internal.get_application_task(app.id, task_id)
    await _internal.apply_application_task_update(task, update)
    return task


@application_api_router.delete("/defined-tasks/{task_id}")
async def deactivate_task(task_id: PydanticObjectId, app=APPLICATION):
    task = await _internal.get_application_task(app.id, task_id)
    await _internal.deactivate_application_task(task)
    return {"detail": "Application has been deleted"}


@application_api_router.post("/events/publish")
async def publish_event(
    request: Request, app=APPLICATION, event_request: _internal.EventDescriptor = Body(...)
):
    event = await _internal.make_and_validate_event(app.id, event_request, request.client.host)
    await _internal.publish_events(event)
    if event.sequence_id:
        await _internal.apply_sequence_updates_on_event(event)
    return {"detail": "Published"}


@application_api_router.post("/sequences")
async def create_sequence(app=APPLICATION, sequence: _internal.SequenceDescriptor = Body(...)):
    return await _internal.create_sequence(app.id, sequence)


@application_api_router.post("/sequences/{sequence_id}/finish")
async def finish_sequence(
    request: Request,
    sequence_id: PydanticObjectId,
    app=APPLICATION,
    update: _internal.FinishSequence = Body(...),
):
    sequence = await _internal.get_sequence(sequence_id, app.id)
    await _internal.finish_sequence(sequence, update, request.client.host)
    return {"detail": "Sequence finished"}


@application_api_router.post("/sequences/{sequence_id}/meta")
async def set_sequence_meta(
    sequence_id: PydanticObjectId,
    app=APPLICATION,
    new_meta: Dict[str, Any] = Body(...),
):
    sequence = await _internal.get_sequence(sequence_id, app.id)
    await _internal.set_sequence_meta(sequence, new_meta)
    return {"detail": "Sequence's meta has been updated"}


@application_api_router.post("/issue-ws-ticket")
async def issue_websocket_token(app=APPLICATION):
    exp = datetime.now() + timedelta(minutes=2)
    return {"ticket": WSTicketModel[Application](exp=exp, sub=app.id).encode(), "exp": exp}


class HelloMessage(_internal.ApplicationClientInfo):
    subscriptions: Optional[List[str]]


def _if_ready_only(f):
    assert inspect.iscoroutinefunction(f)

    @wraps(f)
    async def wrapper(self, *args, **kwargs):
        if not self._ready:
            await self.send_error('You have to send "hello" message first')
            return
        return await f(*args, **kwargs)

    return wrapper


@ws_controller(application_api_router, "/ws")
class AppReportHub(Hub):
    ticket: WSTicketModel[Application] = WSTicket(Application)
    same_ip: Optional[str] = Query(None)
    _app_id: PydanticObjectId
    _connection_info: Optional[ConnectionInfo] = None
    _connection_info_expire: datetime = datetime.min
    _settings_allowed: bool
    _bound_sequences: Optional[List[PydanticObjectId]] = None

    def __init__(self):
        super(AppReportHub, self).__init__()
        self._ready = False

    def _find_bound_sequences(self):
        return EventSequence.find(
            In("_id", self._bound_sequences),
            EventSequence.app_id == self._app_id,
            EventSequence.state == EventSequenceState.IN_PROGRESS,
        )

    async def authenticate(self):
        if self.ticket is None:
            raise HubAuthenticationException("resource key is missing")
        app = await self._app()
        if app is None:
            raise HubAuthenticationException("application could not be found")
        self._app_id = app.id
        self._settings_allowed = app.are_settings_allowed

    def _app(self):
        return Application.get(self.ticket.sub)

    async def on_connected(self):
        await self.send_message(
            "introduction",
            {
                "server_version": VERSION,
                "authentication": "ok",
                "connection_internal_id": self.connection.id,
                "app_id": self._app_id,
            },
        )

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
        if self._connection_info is None:
            return
        self._connection_info.is_connected = False
        self._connection_info.disconnected_at = datetime.utcnow()
        self._connection_info.expires_at = datetime.utcnow() + timedelta()
        await self._connection_info.save_changes()
        await realtime.on_connection_info_changed(self._connection_info)

        if self._bound_sequences and len(self._bound_sequences):
            update = {"frozen": True}
            await self._find_bound_sequences().update(update)
            await realtime.on_sequences_updated(self._app_id, update, self._bound_sequences)

    @bind_message("hello")
    async def on_hello(self, message: HelloMessage):
        if self._ready:
            await self.send_error("you cannot introduce yourself twice, dummy!")
            return
        self._ready = True

        await _internal.get_or_create_connection(self._app_id, message)
        await Server.report_server(
            self.websocket.client, None if message.os_info == "" else message.os_info
        )
        await self._send_connection()

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)

        await self.connection.add_to_group(CG.app(self._app_id))
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

    @bind_message("bind_sequences")
    @_if_ready_only
    async def bind_sequences_to_current_connection(self, sequences: List[PydanticObjectId]):
        self._bound_sequences = sequences
        self._bound_sequences = [
            m.id for m in await self._find_bound_sequences().project(IdProjection).to_list()
        ]
        update = {"frozen": False}
        await self._find_bound_sequences().update(update)
        await realtime.on_sequences_updated(self._app_id, update, self._bound_sequences)
        await self.send_message("bound_to_sequences", self._bound_sequences)
