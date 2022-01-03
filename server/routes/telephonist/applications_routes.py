import hashlib
import inspect
import json
from datetime import datetime, timedelta
from functools import wraps
from typing import *
from uuid import UUID, uuid4

import fastapi
from beanie import PydanticObjectId
from beanie.exceptions import RevisionIdWasChanged
from beanie.operators import Eq
from fastapi import Body, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from starlette import status

from server import VERSION
from server.internal.auth.dependencies import ResourceKey, UserToken
from server.internal.channels import get_channel_layer, wscode
from server.internal.channels.hub import (
    Hub,
    HubAuthenticationException,
    bind_layer_event,
    bind_message,
    ws_controller,
)
from server.internal.channels.wscode import (
    WSC_INCONSISTENT_SIGNATURE,
    WSC_SETTINGS_TYPE_NOT_FOUND,
)
from server.internal.telephonist.application import notify_new_application_settings
from server.internal.telephonist.utils import ChannelGroups, Errors
from server.models.common import IdProjection, Pagination, PaginationResult
from server.models.telephonist import (
    Application,
    ApplicationView,
    AppLog,
    ConnectionInfo,
    OneTimeSecurityCode,
    Server,
    StatusEntry,
)
from server.models.telephonist.application import DetailedApplicationView
from server.models.telephonist.application_settings import (
    application_type_allows_empty_settings,
    get_application_settings_model,
    get_default_settings_for_type,
)
from server.settings import settings
from server.utils.common.json_schema import is_valid_jsonschema

_APPLICATION_NOT_FOUND = "Application not not found"
_APPLICATION_HOSTED = "Application is hosted"
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
    receive_offline: Optional[bool]


class UpdateApplicationSettings(BaseModel):
    new_settings: Dict[str, Any]


class ApplicationsPagination(Pagination):
    ordered_by_options = {"name", "_id"}


@router.get("", responses={200: {"model": PaginationResult[ApplicationView]}})
async def get_applications(
    _=UserToken(),
    args: ApplicationsPagination = Depends(),
) -> PaginationResult[ApplicationView]:
    return await args.paginate(Application, ApplicationView)


@router.post("", status_code=201, responses={201: {"model": IdProjection}})
async def create_application(_=UserToken(), body: CreateApplication = Body(...)):
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


@router.patch("/{app_id}", dependencies=[UserToken()])
async def update_application(app_id: PydanticObjectId, body: UpdateApplication = Body(...)):
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
            await get_channel_layer().group_send(f"app{app.id}", "app_disabled", None)
        app.disabled = body.disabled

    return app


@router.post("/{app_id}/settings", dependencies=[UserToken()])
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


@router.post("/{app_id}/settings/reset", dependencies=[UserToken()])
async def delete_settings(app_id: PydanticObjectId):
    app = await Application.get(app_id)
    if app is None:
        raise HTTPException(404, "Application not found")
    app.settings_revision = uuid4()
    app.settings = get_default_settings_for_type(app.application_type)
    return {"detail": "Settings reset"}


@router.get("/{app_id}/logs")
async def get_app_logs(app_id: PydanticObjectId, before: Optional[datetime] = None, _=UserToken()):
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
    software: str
    software_version: Optional[str]
    compatibility_key: str
    os: str
    pid: int

    def fingerprint(self):
        return (
            "fv1-"
            + hashlib.sha256(
                json.dumps(
                    [
                        sorted(map(str.lower, self.supported_features)),
                        self.compatibility_key,
                        self.assumed_application_type,
                    ]
                ).encode()
            ).hexdigest()
        )


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
    rk: Optional[ResourceKey] = ResourceKey.Depends("application", required=False)
    client_name: Optional[str] = Header(None, alias="user-agent")
    _app_id: PydanticObjectId
    _connection_info: Optional[ConnectionInfo] = None
    _connection_info_expire: datetime = datetime.min
    _settings_allowed: bool

    def __init__(self):
        super(AppReportHub, self).__init__()
        self._ready = False

    async def authenticate(self):
        if self.rk is None:
            raise HubAuthenticationException("resource key is missing")
        app = await self._app()
        if app is None:
            raise HubAuthenticationException("application could not be found")
        self._app_id = app.id
        self._settings_allowed = app.are_settings_allowed

    def _app(self):
        return Application.find_by_key(self.rk.resource_key)

    async def __create_connection(self, fingerprint: str, os: str):
        self._connection_info = ConnectionInfo(
            internal_id=self.connection.id,
            ip=self.websocket.client.host,
            app_id=self._app_id,
            is_connected=True,
            client_name=self.client_name,
            connection_state_fingerprint=fingerprint,
            os=os,
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
            ChannelGroups.public_app(self._app_id),
            "entry_update",
            {
                "entry_name": "connection_info",
                "id": self._connection_info.id,
                "entry": self._connection_info,
                "proto_version": 1,
            },
        )

    async def on_disconnected(self, exc: Exception = None):
        if self._connection_info:
            await self._connection_info.replace()
            self._connection_info.is_connected = False
            self._connection_info.disconnected_at = datetime.utcnow()
            self._connection_info.expires_at = datetime.utcnow() + timedelta(days=1)
            await self._connection_info.save_changes()

    @bind_message("set_settings")
    @_if_ready_only
    async def set_settings(self, message: SetSettings):
        app = await self._app()
        app.settings = message.new_settings
        app.settings_revision = message.settings_stamp
        await notify_new_application_settings(
            await self._app(), message.new_settings, stamp=message.settings_stamp
        )

    @bind_message("hello")
    async def on_hello(self, message: HelloMessage):
        if self._ready:
            await self.send_error("you cannot introduce yourself twice, dummy!")
            return
        self._ready = True

        connection_fingerprint = message.fingerprint()

        # region ensure that connection object exists

        await self.connection.add_to_group(ChannelGroups.public_app(self._app_id))
        connection_info = await ConnectionInfo.find_one(
            ConnectionInfo.ip == self.websocket.client.host,
            ConnectionInfo.app_id == self._app_id,
            Eq(ConnectionInfo.is_connected, False),
        )
        if connection_info is not None:
            if connection_info.is_connected:
                # there's another connection
                if connection_info.connection_state_fingerprint != connection_fingerprint:
                    # TODO add more detail to this message
                    await self.send_error(
                        "It seems like there's already another open connection from"
                        " this application and the fingerprint of that connection is"
                        " different. Make sure that both connections have the same"
                        " settings type or schema and features",
                        "invalid_state_fingerprint",
                    )
                    await self.websocket.close(WSC_INCONSISTENT_SIGNATURE)
                    return
            else:
                # reuse connection info
                connection_info.client_name = message.software
                connection_info.software_version = message.software_version
                connection_info.internal_id = self.connection.id
                connection_info.is_connected = True
                connection_info.connected_at = datetime.utcnow()
                connection_info.expires_at = None
                connection_info.connection_state_fingerprint = connection_fingerprint
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
                    await self.__create_connection(connection_fingerprint, message.os)
        else:
            await self.__create_connection(connection_fingerprint, message.os)

        await Server.report_server(self.websocket.client, None if message.os == "" else message.os)
        await self._send_connection()

        # endregion

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)

        await self.connection.add_to_group(ChannelGroups.private_app(self._app_id))
        await self.send_message(
            "greetings",
            {
                "connection_fingerprint": connection_fingerprint,
                "connections_total": await ConnectionInfo.find(
                    Eq(ConnectionInfo.is_connected, True), ConnectionInfo.app_id == self._app_id
                ).count(),
            },
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
        await self.connection.add_to_group(ChannelGroups.for_event_type(event_type))
        await ConnectionInfo.find({"_id": self._connection_info.id}).update(
            {"$addToSet": {"event_subscriptions": event_type}}
        )
        await self._fetch_connection()
        await self._send_connection()

    @bind_message("unsubscribe")
    @_if_ready_only
    async def unsubscribe(self, event_type: str):
        await self.connection.remove_from_group(ChannelGroups.for_event_type(event_type))
        await ConnectionInfo.find({"_id": self._connection_info.id}).update(
            {"$pull": {"event_subscriptions": event_type}}
        )
        await self._fetch_connection()
        await self._send_connection()

    @bind_message("delete_process")
    @_if_ready_only
    async def delete_process(self, uid: UUID):
        await self._fetch_connection()
        if uid in self._connection_info.statuses:
            del self._connection_info.statuses[uid]
            await self.channel_layer.group_send(
                ChannelGroups.public_app(self._app_id),
                "connection_status_entry_delete",
                {"uid": uid},
            )
            await self._connection_info.save_changes()

    @bind_message("update_process")
    @_if_ready_only
    async def update_process(self, m: UpdateProcess):
        await self._fetch_connection()
        entry = self._connection_info.statuses.get(m.uid)
        if entry:
            entry.tasks_total = m.tasks_total or entry.tasks_total
            entry.title = m.title or entry.title
            entry.subtitle = m.subtitle or entry.subtitle
            entry.is_intermediate = m.is_intermediate or entry.is_intermediate
            entry.progress = m.progress or entry.progress
        else:
            entry = StatusEntry(
                progress=m.progress,
                tasks_total=m.tasks_total,
                is_intermediate=m.is_intermediate or False,
                title=m.title,
                subtitle=m.subtitle,
            )
            self._connection_info[m.uid] = entry
        await self._connection_info.save_changes()
        await self.channel_layer.group_send(
            ChannelGroups.public_app(self._app_id),
            "connection_status_entry",
            {"uid": m.uid, "entry": entry},
        )
