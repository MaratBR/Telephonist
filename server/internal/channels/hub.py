import asyncio
import inspect
import logging
from json import JSONDecodeError
from typing import *

from fastapi import APIRouter
from pydantic import ValidationError, parse_obj_as, Field
from pydantic.typing import is_classvar
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from server.internal.channels.layer import (
    ChannelLayer,
    Connection,
    get_channel_layer,
)
from server.models.common import AppBaseModel
from server.utils.annotations import AnnotatedMember, create_annotation

WS_CBV_KEY = "__ws_cbv_class__"
WS_CBV_CALL_NAME = "__ws_cbv_call__"
WS_CBV_MESSAGE_HANDLER = "__ws_cbv_message__"
WS_CBV_INTERNAL_EVENTS = "__ws_cbv_internal_events__"


class HubHandlerMeta(NamedTuple):
    msg_type: str
    typehint: type


class HubHandlerCache(NamedTuple):
    method_name: str
    typehint: type


_logger = logging.getLogger("telephonist.channels")


class HubException(Exception):
    pass


class HubAuthenticationException(HubException):
    pass


class InvalidMessageException(HubException):
    pass


# https://github.com/dmontagu/fastapi-utils/blob/master/fastapi_utils/cbv.py


def ws_controller(router: APIRouter, path: str, name: Optional[str] = None):
    def decorator(cls):
        add_ws_controller(cls, router, path, name)
        return cls

    return decorator


def add_ws_controller(
    cls: Type["Hub"], router: APIRouter, path: str, name: Optional[str] = None
):
    _init_ws_cbv(cls)
    caller = getattr(cls, WS_CBV_CALL_NAME)
    router.add_api_websocket_route(path, caller, name=name)


bind_event = create_annotation(str, "bind_event")
bind_message = create_annotation(str, "bind_message")


class HandlerInfo(NamedTuple):
    typehint: Optional[Any]
    message_type: str
    method_name: str

    @staticmethod
    def _get_argument_type(f):
        sig = inspect.signature(f)
        message_params = [
            p
            for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty and p.name != "self"
        ]
        if len(message_params) > 1:
            raise TypeError(
                "Invalid signature - only one or zero parameters without"
                " default value allowed"
            )
        if len(message_params) == 0:
            return None
        return message_params[0]

    @classmethod
    def from_method(cls, method: AnnotatedMember[str]):
        return cls(
            typehint=cls._get_argument_type(method.member),
            message_type=method.metadata,
            method_name=method.name
        )


class HubMessage(AppBaseModel):
    data: Any = Field(alias="d")
    msg_type: str = Field(alias="t")


class Hub:
    _connection: Optional[Connection]
    _channel_layer: ChannelLayer
    websocket: WebSocket

    """
    handlers for messages defined with bind_message
    """
    _message_handlers: ClassVar[dict[str, HandlerInfo]]
    _static_event_handlers: ClassVar[dict[str, HandlerInfo]]

    @property
    def connection(self):
        return self._connection

    @property
    def channel_layer(self):
        return self._channel_layer

    def __init__(self):
        self._connection = None

    def __init_subclass__(cls, **kwargs):
        cls._message_handlers = {
            m.name: HandlerInfo.from_method(m)
            for m in bind_message.methods(cls)
        }
        cls._static_event_handlers = {
            m.name: HandlerInfo.from_method(m) for m in bind_event.methods(cls)
        }

    async def on_exception(self, exception: Exception):
        """
        Метод, вызываемый при возникновении неожиданного исключения.
        :param exception:
        """
        await self.send_error(exception, kind="internal")
        _logger.exception(str(exception))

    async def read_message(self) -> HubMessage:
        try:
            json_obj = await self.websocket.receive_json()
        except AssertionError:
            # TODO ????
            # not sure what to do here and also don't remember why is this here
            raise WebSocketDisconnect()
        except JSONDecodeError:
            raise InvalidMessageException("invalid message format")

        try:
            assert isinstance(
                json_obj, dict
            ), "Received message must be a JSON object"
            return HubMessage(**json_obj)
        except (AssertionError, ValidationError) as exc:
            raise InvalidMessageException(str(exc))

    async def send_message(self, msg_type: str, data: Any):
        await self.connection.send(msg_type, data)

    async def send_error(self, error: Any, kind: Optional[str] = None):
        """
        Отправляет ошибку клиенту.
        :param error: Сообщение об ошибке, о котором нужно знать клиенту.
        :param kind: Дополнительный параметр указывающий тип ошибки.
        """
        if isinstance(error, Exception):
            error_object = {
                "error_type": kind or "500",
                "exception": type(error).__name__,
                "error": str(error),
            }
        else:
            error_object = {"error_type": kind or "custom", "error": error}
        await self.connection.send("error", error_object)

    async def authenticate(self):
        pass

    async def on_connected(self):
        pass

    async def on_disconnected(self, exc: Exception = None):
        pass

    async def _subscribe_to_events(self):
        for method_name, info in self._static_event_handlers.items():
            pass

    async def _run(self):
        if self.websocket.application_state == WebSocketState.DISCONNECTED:
            return
        self._channel_layer = get_channel_layer()

        try:
            await self.authenticate()
        except HubAuthenticationException as exc:
            await self.websocket.accept()
            await self.send_error(str(exc), "authentication_failed")
            await self.websocket.close()
            return

        await self.websocket.accept()
        await self._subscribe_to_events()

        # create new connection and star listening for incoming messages
        async with self.channel_layer.new_connection() as connection:
            self._connection = connection
            try:
                await self.on_connected()
                await self._main_loop()
            except Exception as exc:
                if not isinstance(exc, WebSocketDisconnect):
                    await self.on_exception(exc)
                    await self.websocket.close(
                        1000 if isinstance(exc, WebSocketDisconnect) else 1011
                    )
                await self.on_disconnected(exc)

    async def _main_loop(self):
        task = asyncio.create_task(self._messages_loop())
        try:
            await self._receiver_loop()
        finally:
            task.cancel()

    async def _messages_loop(self):
        try:
            async for message in self._connection.queued_messages():
                if message["type"] == "disconnect":
                    await self.websocket.close()
                elif message["type"] == "message":
                    await self.websocket.send_text(
                        HubMessage(
                            t=message["message"]["type"],
                            d=message["message"]["data"],
                        ).json()
                    )
                elif message["type"] == "event":
                    await self._handle_event(message["event"])
                else:
                    _logger.warning(
                        "Received unknown message from the connection"
                        f" object's message queue: {message}"
                    )
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, message: HubMessage):
        """
        Dispatches incoming message to the appropriate handler within the hub.
        """
        handler = self._message_handlers.get(message.msg_type)
        if handler:
            await self._call_handler(handler, message.data)

    async def _handle_event(self, event: dict):
        handler = self._static_event_handlers.get(event["name"])
        if handler:
            await self._call_handler(handler, event["data"])

    async def _call_handler(self, info: HandlerInfo, arg: Any):
        method = getattr(self, info.method_name)
        if info.typehint is not Any:
            try:
                message_data = parse_obj_as(info.typehint, arg)
            except ValidationError as exc:
                await self.send_error(str(exc), "invalid_data")
                return
        else:
            message_data = arg
        try:
            await _call_method(method, message_data)
        except Exception as exc:
            await self.on_exception(exc)

    async def _receiver_loop(self):
        while True:
            if self.websocket.state == WebSocketState.DISCONNECTED:
                raise WebSocketDisconnect()

            try:
                message = await self.read_message()
            except InvalidMessageException as err:
                await self.send_error(err)
                continue
            await self._handle_message(message)


async def _call_method(method, *args, **kwargs):
    v = method(*args, **kwargs)
    if inspect.isawaitable(v):
        v = await v
    return v


def _init_ws_cbv(cls: Type["Hub"]):
    if getattr(cls, WS_CBV_KEY, False):
        return  # already initialized

    # modify __init__
    init: Callable[..., Any] = cls.__init__
    signature = inspect.signature(init)
    parameters = list(signature.parameters.values())[
        1:
    ]  # drop `self` parameter
    call_parameters = [
        x
        for x in parameters
        if x.kind
        not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
    ]
    dependency_names: List[str] = []
    for name, hint in get_type_hints(cls).items():
        if is_classvar(hint) or name.startswith("_"):
            continue
        call_parameters.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=hint,
                default=getattr(cls, name, Ellipsis),
            )
        )
        dependency_names.append(name)
    call_signature = signature.replace(parameters=call_parameters)

    async def ws_cbv_call(*args: Any, **kwargs: Any) -> None:
        fields = {}
        for dep in dependency_names:
            fields[dep] = kwargs.pop(dep)
        hub = cls(*args, **kwargs)  # noqa
        for dep in dependency_names:
            setattr(hub, dep, fields[dep])
        await hub._run()  # noqa

    setattr(ws_cbv_call, "__signature__", call_signature)
    setattr(cls, WS_CBV_CALL_NAME, staticmethod(ws_cbv_call))
    setattr(cls, WS_CBV_KEY, True)
