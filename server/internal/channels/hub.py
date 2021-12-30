import asyncio
import inspect
from collections import namedtuple
from typing import *

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel, ValidationError, parse_obj_as
from pydantic.typing import is_classvar
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from server.internal.channels.layer import ChannelLayer, Connection, get_channel_layer

WS_CBV_KEY = "__ws_cbv_class__"
WS_CBV_CALL_NAME = "__ws_cbv_call__"
WS_CBV_MESSAGE_HANDLER = "__ws_cbv_message__"
HubHandlerMeta = namedtuple("HubHandlerMeta", ("msg_type", "typehint"))
HubHandlerCache = namedtuple("HubHandlerCache", ("method_name", "typehint"))


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


def add_ws_controller(cls: Type["Hub"], router: APIRouter, path: str, name: Optional[str] = None):
    _init_ws_cbv(cls)
    caller = getattr(cls, WS_CBV_CALL_NAME)
    router.add_api_websocket_route(router.prefix + path, caller, name=name)


def bind_message(msg_type: Optional[str] = None):
    if msg_type is not None and not isinstance(msg_type, str):
        raise TypeError("msg_type must be a string or None")

    def decorator(fn):
        nonlocal msg_type
        if msg_type is None:
            if fn.__name__.startswith("on_"):
                msg_type = fn.__name__[3:]
            else:
                msg_type = fn.__name__
        sig = inspect.signature(fn)
        params = sig.parameters.copy()
        if "self" in params:
            del params["self"]
        message_params = [p for p in params.values() if p.default is inspect.Parameter.empty]
        if len(message_params) > 1:
            raise TypeError(
                "Invalid message handler signature - only one or zero parameters"
                " without default value allowed"
            )
        if len(message_params) == 0:
            typehint = None
        else:
            typehint = message_params[0].annotation or Any
        setattr(
            fn,
            WS_CBV_MESSAGE_HANDLER,
            HubHandlerMeta(msg_type=msg_type, typehint=typehint),
        )
        return fn

    return decorator


class HubMessage(BaseModel):
    data: Any
    msg_type: str


class Hub:
    _connection: Optional[Connection]
    _channel_layer: ChannelLayer
    websocket: WebSocket
    _static_handlers: ClassVar[Dict[str, str]]

    @property
    def connection(self):
        return self._connection

    @property
    def channel_layer(self):
        return self._channel_layer

    def __init__(self):
        self._local_handlers = self._static_handlers.copy()
        self._connection = None

    def __init_subclass__(cls, **kwargs):
        methods = inspect.getmembers(
            cls,
            lambda m: inspect.isfunction(m) and hasattr(m, WS_CBV_MESSAGE_HANDLER),
        )
        handlers = {}
        for method_name, method in methods:
            meta: HubHandlerMeta = getattr(method, WS_CBV_MESSAGE_HANDLER)
            handlers[meta.msg_type] = HubHandlerCache(
                typehint=meta.typehint, method_name=method_name
            )
        cls._static_handlers = handlers

    async def on_exception(self, exception: Exception):
        """
        Метод, вызываемый при возникновении неожиданного исключения.
        :param exception:
        """
        await self.send_error(exception, kind="internal")

    async def read_message(self) -> dict:
        try:
            json_obj = await self.websocket.receive_json()
        except (AssertionError, WebSocketDisconnect) as exc:
            if isinstance(exc, AssertionError):
                raise WebSocketDisconnect()
            raise

        try:
            assert isinstance(json_obj, dict), "Received message must be a JSON object"
            assert (
                "msg_type" in json_obj and "data" in json_obj
            ), 'Message object does not contain "data" and "msg_type" keys'
            assert isinstance(json_obj["msg_type"], str), 'Raw message\'s "type" is not a string'
            message = {"msg_type": json_obj["msg_type"], "data": json_obj["data"]}
            logger.debug(
                f"recv from {self.websocket.client.host}:{self.websocket.client.port} < {message}"
            )
            return message
        except AssertionError as exc:
            raise InvalidMessageException(str(exc))

    async def send_message(self, msg_type: str, data: Any):
        message = HubMessage(msg_type=msg_type, data=data)
        await self.websocket.send_text(message.json())
        logger.debug(
            f"sent to {self.websocket.client.host}:{self.websocket.client.port} > {message.json()}"
        )

    async def send_error(self, error: Any, kind: Optional[str] = None):
        """
        Отправляет ошибку клиенту.
        :param error: Сообщение об ошибке, о котором нужно знать клиенту.
        :param kind: Дополнительный параметр указывающий тип ошибки.
        """
        if isinstance(error, Exception):
            error_object = {
                "error_type": "500",
                "exception": type(error).__name__,
                "error": str(error),
            }
        else:
            error_object = {"error_type": kind or "custom", "error": error}
        await self.send_message("error", error_object)

    async def authenticate(self):
        pass

    async def on_connected(self):
        pass

    async def on_disconnected(self, exc: Exception = None):
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

        try:
            async with self.channel_layer.new_connection() as connection:
                self._connection = connection
                try:
                    await self.on_connected()
                    await self._main_loop()
                except WebSocketDisconnect as exc:
                    await self.on_disconnected(exc)
        except:
            raise

    async def _main_loop(self):
        task = asyncio.create_task(self._external_messages_loop())
        try:
            await self._receiver_loop()
        finally:
            task.cancel()

    async def _external_messages_loop(self):
        try:
            async for message in self._connection.queued_messages():
                if message["msg_type"] == "__disconnect__":
                    await self.websocket.close()
                else:
                    await self.send_message(message["msg_type"], message["data"])
        except asyncio.CancelledError:
            pass

    async def _receiver_loop(self):
        while True:
            if self.websocket.state == WebSocketState.DISCONNECTED:
                raise WebSocketDisconnect()

            try:
                message = await self.read_message()
            except InvalidMessageException as err:
                await self.send_error(err)
                continue
            await self._dispatch_message(message)

    async def _dispatch_message(self, message: dict):
        """
        Dispatches incoming message to the appropriate handler withing hub.

        :param message: message with keys - "msg_type" and "message"
        """
        handler = self._local_handlers.get(message["msg_type"])
        if handler:
            method = getattr(self, handler.method_name)
            message_data = message["data"]
            if handler.typehint is not Any:
                try:
                    message_data = parse_obj_as(handler.typehint, message["data"])
                except ValidationError as exc:
                    await self.send_error(exc)
            try:
                await _call_method(method, message_data)
            except Exception as exc:
                await self.on_exception(exc)


async def _call_method(method, *args, **kwargs):
    v = method(*args, **kwargs)
    if inspect.isawaitable(v):
        v = await v
    return v


def _init_ws_cbv(cls: Type["Hub"]):
    if getattr(cls, WS_CBV_KEY, False):
        return  # already initialized

    init: Callable[..., Any] = cls.__init__
    signature = inspect.signature(init)
    parameters = list(signature.parameters.values())[1:]  # drop `self` parameter
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