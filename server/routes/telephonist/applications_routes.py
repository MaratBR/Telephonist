import inspect
from datetime import datetime, timedelta
from functools import wraps
from typing import *
from uuid import UUID, uuid4

import fastapi
from beanie import PydanticObjectId
from beanie.exceptions import RevisionIdWasChanged
from beanie.operators import Eq, In
from fastapi import Body, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from starlette import status

from server import VERSION
from server.internal.auth.dependencies import AccessToken
from server.internal.auth.schema import bearer, require_bearer
from server.internal.channels import WSTicket, WSTicketModel, get_channel_layer, wscode
from server.internal.channels.hub import (
    Hub,
    HubAuthenticationException,
    bind_message,
    ws_controller,
)
from server.internal.telephonist import realtime
from server.internal.telephonist.application import notify_new_application_settings
from server.internal.telephonist.utils import CG, Errors
from server.models.common import IdProjection, Pagination, PaginationResult
from server.models.telephonist import (
    Application,
    ApplicationView,
    AppLog,
    ConnectionInfo,
    EventSequence,
    EventSequenceState,
    OneTimeSecurityCode,
    Server,
)
from server.models.telephonist.application import DetailedApplicationView
from server.models.telephonist.application_settings import (
    get_application_settings_model,
    get_default_settings_for_type,
)
from server.settings import settings

_APPLICATION_NOT_FOUND = "Application not not found"
router = fastapi.APIRouter(prefix="/applications", tags=["applications"])


class CreateApplication(BaseModel):
    name: str
    description: Optional[str] = Field(max_length=400)
    tags: Optional[List[str]]
    disabled: bool = False
    application_type: str = Application.ARBITRARY_TYPE


class UpdateApplication(BaseModel):
    name: Optional[str]
    description: Optional[str] = Field(max_length=400)
    disabled: Optional[bool]
    tags: Optional[List[str]]


class UpdateApplicationSettings(BaseModel):
    new_settings: Dict[str, Any]


class ApplicationsPagination(Pagination):
    ordered_by_options = {"name", "_id"}


@router.get(
    "", responses={200: {"model": PaginationResult[ApplicationView]}}, dependencies=[AccessToken()]
)
async def get_applications(
    args: ApplicationsPagination = Depends(),
) -> PaginationResult[ApplicationView]:
    return await args.paginate(Application, ApplicationView)


@router.post("", status_code=201, responses={201: {"model": IdProjection}})
async def create_application(_=AccessToken(), body: CreateApplication = Body(...)):
    if (
        body.application_type not in (Application.ARBITRARY_TYPE, Application.HOST_TYPE)
        and not settings.allow_custom_application_types
    ):
        raise HTTPException(422, "invalid application type, custom application types are disabled")
    if await Application.find(Application.name == body.name).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Application with given name already exists",
        )
    app = Application(
        name=body.name,
        description=body.description,
        disabled=body.disabled,
        tags=[] if body.tags is None else list(set(body.tags)),
        application_type=body.application_type,
        settings=get_default_settings_for_type(body.application_type),
    )
    await app.save()
    return IdProjection(_id=app.id)


@router.post("/issue-ws-ticket")
async def issue_ws_ticket(key: str = Depends(require_bearer)):
    app = await Application.find_by_key(key)
    if app is None:
        raise HTTPException(404, "application not found")
    exp = datetime.now() + timedelta(minutes=2)
    return {"ticket": WSTicketModel[Application](exp=exp, sub=app.id).encode(), "exp": exp}


@router.get("/{app_id}")
async def get_application(app_id: PydanticObjectId):
    app = await Application.find_one({"_id": app_id}).project(DetailedApplicationView)
    if app is None:
        raise HTTPException(404, "Application not found")
    connections = await ConnectionInfo.find(ConnectionInfo.app_id == app.id).to_list()
    return {"app": app, "connections": connections}


@router.get("/name/{app_name}")
async def get_application(app_name: str):
    return Errors.raise404_if_none(
        await Application.find_one(Application.name == app_name).project(ApplicationView),
        _APPLICATION_NOT_FOUND,
    )


@router.patch("/{app_id}", dependencies=[AccessToken()])
async def update_application(app_id: PydanticObjectId, body: UpdateApplication = Body(...)):
    app = Errors.raise404_if_none(await Application.get(app_id), _APPLICATION_NOT_FOUND)
    app.name = body.name or app.name
    app.description = body.description or app.description
    app.tags = body.tags or app.tags

    await app.save_changes()

    if body.disabled is not None and body.disabled != app.disabled:
        if body.disabled:
            await get_channel_layer().group_send(f"app{app.id}", "app_disabled", None)
        app.disabled = body.disabled

    return ApplicationView(**app.dict(by_alias=True))


@router.post("/{app_id}/settings", dependencies=[AccessToken()])
async def update_application_settings(app_id: PydanticObjectId, body: UpdateApplicationSettings):
    app = await Application.get(app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    model = get_application_settings_model(app.application_type)
    try:
        app.settings = model(body)
    except ValidationError:
        # TODO detailed response
        raise HTTPException(
            422, f'invalid settings format for application type "{app.application_type}"'
        )
    try:
        await app.replace()
    except RevisionIdWasChanged:
        raise HTTPException(status.HTTP_409_CONFLICT, "application seems to have changed recently")
    return {"detail": "Settings updated successfully"}


@router.post("/{app_id}/settings/reset", dependencies=[AccessToken()])
async def delete_settings(app_id: PydanticObjectId):
    app = await Application.get(app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    app.settings_revision = uuid4()
    app.settings = get_default_settings_for_type(app.application_type)
    return {"detail": "Settings reset"}


@router.get("/{app_id}/logs")
async def get_app_logs(
    app_id: PydanticObjectId, before: Optional[datetime] = None, _=AccessToken()
):
    Errors.raise404_if_false(await Application.find({"_id": app_id}).exists())
    if before is None:
        logs = AppLog.find()
    else:
        logs = AppLog.find_before(before)
    logs = await logs.limit(100).to_list()
    return {"before": before, "logs": logs}


class CRRequest(BaseModel):
    client_name: str


@router.post("/code-register")
async def request_code_registration(body: CRRequest = Body(...)):
    code = await OneTimeSecurityCode.new("new_app_code", body.client_name)
    return {
        "code": code.id,
        "expires_at": code.expires_at,
        "ttl": OneTimeSecurityCode.DEFAULT_LIFETIME.total_seconds(),
    }


@router.post("/code-register/confirm/{code}")
async def confirm_code_registration(code: str):
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


@router.post("/code-register/finish/{code}", response_model=CRFinishResponse)
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


class SettingsDescriptor(BaseModel):
    settings: Optional[Any]
    settings_revision: Optional[int]


class HelloMessage(BaseModel):
    subscriptions: Optional[List[str]]
    assumed_application_type: str
    supported_features: List[str]
    client_name: str
    client_version: Optional[str]
    compatibility_key: str
    machine_id: str
    instance_id: str
    os: str
    pid: int


class UpdateProcess(BaseModel):
    uid: UUID
    title: Optional[str]
    subtitle: Optional[str]
    progress: Optional[str]
    is_intermediate: Optional[bool]
    tasks_total: Optional[int]


class SetSettings(BaseModel):
    new_settings: Dict[str, Any]
    settings_stamp: UUID


def _if_ready_only(f):
    assert inspect.iscoroutinefunction(f)

    @wraps(f)
    async def wrapper(self, *args, **kwargs):
        if not self._ready:
            await self.send_error('You have to send "hello" message first')
            return
        return await f(*args, **kwargs)

    return wrapper


@ws_controller(router, "/ws")
class AppReportHub(Hub):
    ticket: WSTicketModel[Application] = WSTicket(Application)
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
            In("state", [EventSequenceState.PENDING, EventSequenceState.IN_PROGRESS]),
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

    async def __create_connection(
        self,
        *,
        os: str,
        machine_id: str,
        instance_id: str,
        client_name: str,
        client_version: str,
    ):
        self._connection_info = ConnectionInfo(
            ip=self.websocket.client.host,
            app_id=self._app_id,
            is_connected=True,
            os=os,
            machine_id=machine_id,
            instance_id=instance_id,
            client_name=client_name,
            client_version=client_version,
        )
        await self._connection_info.insert()

    async def _fetch_connection(self):
        if datetime.now() > self._connection_info_expire:
            self._connection_info = await ConnectionInfo.get(self._connection_info.id)
            self._connection_info_expire = datetime.now() + timedelta(seconds=20)
            assert self._connection_info, "ConnectionInfo object suddenly disappeared from database"

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
        await self._connection_info.replace()
        self._connection_info.is_connected = False
        self._connection_info.disconnected_at = datetime.utcnow()
        self._connection_info.expires_at = datetime.utcnow() + timedelta()
        await self._connection_info.save_changes()

        if not await ConnectionInfo.find(
            ConnectionInfo.app_id == self._app_id, Eq("is_connected", True)
        ).exists():
            # put all sequences of this application in frozen state
            ConnectionInfo.find()

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

        # region ensure that connection object exists

        connection_info = await ConnectionInfo.find_one(
            ConnectionInfo.ip == self.websocket.client.host,
            ConnectionInfo.app_id == self._app_id,
            Eq(ConnectionInfo.is_connected, False),
        )
        if connection_info is not None:
            # reuse connection info
            connection_info.client_name = message.client_name
            connection_info.client_version = message.client_version
            connection_info.is_connected = True
            connection_info.connected_at = datetime.utcnow()
            connection_info.expires_at = None
            connection_info.os = message.os
            try:
                await connection_info.replace()
                self._connection_info = connection_info
            except RevisionIdWasChanged:
                logger.warning(
                    "failed to update already existing connection due to the"
                    " RevisionIdWasChanged error (id of connection in question - {}, related"
                    " application - {})",
                    connection_info.id,
                    self._app_id,
                )
                await self.__create_connection(
                    os=message.os,
                    instance_id=message.instance_id,
                    machine_id=message.machine_id,
                    client_name=message.client_name,
                    client_version=message.client_version,
                )
        else:
            await self.__create_connection(
                os=message.os,
                instance_id=message.instance_id,
                machine_id=message.machine_id,
                client_name=message.client_name,
                client_version=message.client_version,
            )

        await Server.report_server(self.websocket.client, None if message.os == "" else message.os)
        await self._send_connection()

        # endregion

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)

        await self.connection.add_to_group(CG.app(self._app_id))
        await self.send_message(
            "greetings",
            {
                "connections_total": await ConnectionInfo.find(
                    Eq(ConnectionInfo.is_connected, True), ConnectionInfo.app_id == self._app_id
                ).count(),
            },
        )

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)

    @bind_message("set_settings")
    @_if_ready_only
    async def set_settings(self, message: SetSettings):
        app = await self._app()
        app.settings = message.new_settings
        app.settings_revision = message.settings_stamp
        await notify_new_application_settings(
            self._app_id, message.new_settings, stamp=message.settings_stamp
        )

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
        await ConnectionInfo.find({"_id": self._connection_info.id}).update(
            {"$addToSet": {"event_subscriptions": event_type}}
        )
        await self._fetch_connection()
        await self._send_connection()

    @bind_message("unsubscribe")
    @_if_ready_only
    async def unsubscribe(self, event_type: str):
        await self.connection.remove_from_group(CG.events(event_type=event_type))
        await ConnectionInfo.find({"_id": self._connection_info.id}).update(
            {"$pull": {"event_subscriptions": event_type}}
        )
        await self._fetch_connection()
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
