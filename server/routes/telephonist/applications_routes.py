import hashlib
import inspect
import json
from datetime import datetime, timedelta
from functools import wraps
from typing import *

import fastapi
import jsonschema
from beanie import PydanticObjectId
from beanie.exceptions import RevisionIdWasChanged
from beanie.operators import Eq
from fastapi import Body, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from starlette import status

from server import VERSION
from server.internal.auth.dependencies import ResourceKey, UserToken
from server.internal.channels import get_channel_layer, wscode
from server.internal.channels.hub import (
    Hub,
    HubAuthenticationException,
    bind_message,
    ws_controller,
)
from server.internal.channels.wscode import (
    WSC_INCONSISTENT_SIGNATURE,
    WSC_SETTINGS_TYPE_NOT_FOUND,
)
from server.internal.telephonist.application_settings_registry import (
    builtin_application_settings,
)
from server.internal.telephonist.utils import ChannelGroups, Errors
from server.models.common import IdProjection, Pagination, PaginationResult
from server.models.telephonist import (
    Application,
    ApplicationView,
    AppLog,
    ConnectionInfo,
    OneTimeSecurityCode,
    Server,
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


class GetApplicationTokenRequest(BaseModel):
    token: str


class UpdateApplication(BaseModel):
    name: Optional[str]
    description: Optional[str] = Field(max_length=400)
    disabled: Optional[bool]
    receive_offline: Optional[bool]


class DetailedApplicationView(BaseModel):
    class Settings(BaseModel):
        value: Optional[Any]
        type: Optional[Any]
        schema_: Optional[Any] = Field(alias="schema")

    app: ApplicationView
    settings: Settings
    connections: List[ConnectionInfo]


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
    )
    await app.save()
    return IdProjection(_id=app.id)


@router.get("/builtin-settings")
def get_built_in_settings():
    return builtin_application_settings


@router.get("/{app_id}", response_model=DetailedApplicationView)
async def get_application(app_id: PydanticObjectId):
    app = await Application.find_one({"_id": app_id})
    if app is None:
        raise HTTPException(404, "Application not found")
    connections = await ConnectionInfo.find(ConnectionInfo.app_id == app.id).to_list()
    return {
        "app": app,
        "connections": connections,
        "settings": {
            "value": app.settings,
            "type": app.settings_type,
            "schema": app.settings_schema or builtin_application_settings.get(app.settings_type),
        },
    }


@router.get("/name/{app_name}")
async def get_application(app_name: str):
    return Errors.raise404_if_none(
        await Application.find_one(Application.name == app_name).project(ApplicationView),
        _APPLICATION_NOT_FOUND,
    )


@router.patch("/{app_id}")
async def update_application(
    app_id: PydanticObjectId,
    body: UpdateApplication = Body(...),
    user_token=UserToken(),
):
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


@router.get(
    "/{app_id}/logs",
)
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
    code.expires_at = datetime.now() + timedelta(days=10)
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
    settings_schema: Union[str, Dict[str, Any]]
    supported_features: List[str]
    software: str
    software_version: Optional[str]
    os: str
    pid: int

    def fingerprint(self):
        return (
            "fv1-"
            + hashlib.sha256(
                json.dumps(
                    [
                        sorted(map(str.lower, self.supported_features)),
                        self.settings_schema,
                    ]
                ).encode()
            ).hexdigest()
        )


@ws_controller(router, "/ws")
class AppReportHub(Hub):
    rk: Optional[ResourceKey] = ResourceKey.Depends("application", required=False)
    client_name: Optional[str] = Header(None, alias="user-agent")
    _app_id: PydanticObjectId
    _connection_info: Optional[ConnectionInfo] = None

    def __init__(self):
        super(AppReportHub, self).__init__()
        self._ready = False

    def _if_ready_only(self, f):
        assert inspect.iscoroutinefunction(f)

        @wraps(f)
        async def wrapper(*args, **kwargs):
            if not self._ready:
                await self.send_error('You have to send "hello" message first')
                return
            return await f(*args, **kwargs)

        return wrapper

    async def authenticate(self):
        if self.rk is None:
            raise HubAuthenticationException("resource key is missing")
        app = await self._app()
        if app is None:
            raise HubAuthenticationException("application could not be found")
        self._app_id = app.id

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
        self._connection_info = await ConnectionInfo.get(self._connection_info.id)
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
            ChannelGroups.app_updates(self._app_id),
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
            self._connection_info.disconnected_at = datetime.now()
            self._connection_info.expires_at = datetime.now() + timedelta(days=1)
            await self._connection_info.save_changes()

    @bind_message("set_settings")
    async def set_settings(self, new_settings: Dict[str, Any]):
        pass

    @bind_message("hello")
    async def on_hello(self, message: HelloMessage):
        if self._ready:
            await self.send_error("you cannot introduce yourself twice, dummy!")
            return
        self._ready = True

        # region check that schema is valid

        if isinstance(message.settings_schema, str):
            if message.settings_schema not in builtin_application_settings:
                await self.send_error("invalid setting schema type: {}", message.settings_schema)
                await self.websocket.close(WSC_SETTINGS_TYPE_NOT_FOUND)
                return
        else:
            if not is_valid_jsonschema(message.settings_schema):
                await self.send_error(
                    "invalid settings schema: provided schema object did not pass the"
                    " validation, validation is done against"
                    f" {settings.jsonschema_validator}"
                )
                await self.websocket.close(WSC_SETTINGS_TYPE_NOT_FOUND)
                return

        # endregion

        connection_fingerprint = message.fingerprint()

        # region ensure that connection object exists

        await self.connection.add_to_group(ChannelGroups.app_events(self._app_id))
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
                connection_info.connected_at = datetime.now()
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

        # endregion

        if message.subscriptions:
            await self.set_subscriptions(message.subscriptions)

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
    async def set_subscriptions(self, subscriptions: List[str]):
        await self._fetch_connection()
        await self._connection_info.update({"event_subscriptions": subscriptions})
        await self._send_connection()

    @bind_message("subscribe")
    async def subscribe(self, event_type: str):
        await ConnectionInfo.find({"_id": self._connection_info.id}).update(
            {"$addToSet": {"event_subscriptions": event_type}}
        )
        await self._fetch_connection()
        await self._send_connection()

    @bind_message("unsubscribe")
    async def unsubscribe(self, event_type: str):
        await ConnectionInfo.find({"_id": self._connection_info.id}).update(
            {"$pull": {"event_subscriptions": event_type}}
        )
        await self._fetch_connection()
        await self._send_connection()