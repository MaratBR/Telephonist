import asyncio
import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
    AsyncIterable,
    Awaitable,
    Optional,
    Union,
)

import nanoid
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from server.common.channels.backplane import BackplaneBase, get_backplane
from server.common.models import AppBaseModel
from server.dependencies import get_application

_PREFIX = "cl/"
_PREFIX_MESSAGE = _PREFIX + "message/"
_PREFIX_EVENT = _PREFIX + "event/"

_logger = logging.getLogger("telephonist.channels")


class HubError(Exception):
    pass


class ConnectionStateError(HubError):
    pass


class HubProxy(ABC):
    @abstractmethod
    def _send(self, msg_type: str, message: Any) -> Awaitable[None]:
        ...

    def send(self, msg_type: str, message: Any):
        if isinstance(message, AppBaseModel):
            message = message.dict(by_alias=True)
        return self._send(msg_type, message)


class Connection(HubProxy):
    def __init__(self, backplane: BackplaneBase):
        self.id = nanoid.generate()
        self._backplane = backplane
        self._queue: asyncio.Queue[
            Union[tuple[str, Any], dict]
        ] = asyncio.Queue()
        self.disconnected_at: Optional[datetime] = None
        self._groups = set()
        self._events = set()
        self._active = False

    async def _send(self, msg_type: str, message: Any):
        await self._queue.put(
            {"type": "message", "message": {"type": msg_type, "data": message}}
        )

    async def disconnect(self):
        await self._queue.put({"type": "disconnect"})

    async def queued_messages(self) -> AsyncIterable[dict]:
        assert self._active, "Connection is not active"

        while True:
            try:
                message = await self.get_next_message()
            except Exception as exc:
                continue
            if message:
                yield message

    async def get_next_message(self) -> Optional[dict]:
        item = await self._queue.get()

        if isinstance(item, dict):
            return item
        assert isinstance(item, tuple), "received message is not a tuple"
        channel, data = item
        if channel.startswith(_PREFIX_MESSAGE):
            data["topic"] = channel[len(_PREFIX_MESSAGE) :]
        return data

    async def __aenter__(self):
        assert (
            not self._active
        ), "Connection cannot be activated if it's already active"
        self._active = True
        for group in self._groups:
            await self._backplane.attach_queue(
                _PREFIX_MESSAGE + group, self._queue
            )

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        assert (
            self._active
        ), "Connection cannot be deactivate when it's already deactivated"
        self._active = False
        self.disconnected_at = datetime.now()
        for group in self._groups:
            await self._backplane.detach_queue(
                _PREFIX_MESSAGE + group, self._queue
            )

    async def remove_all_groups(self):
        # TODO проверить на race condition
        if self._active:
            for g in self._groups:
                await self._backplane.detach_queue(
                    _PREFIX_MESSAGE + g, self._queue
                )
        self._groups.clear()

    async def add_event(self, event: str):
        if event in self._events:
            return
        self._events.add(event)
        await self._backplane.attach_queue(_PREFIX_EVENT + event, self._queue)

    async def remove_event(self, event: str):
        if event in self._events:
            return
        self._events.add(event)
        await self._backplane.attach_queue(_PREFIX_EVENT + event, self._queue)

    async def add_to_group(self, group: str):
        if group in self._groups:
            return
        self._groups.add(group)
        if self._active:
            await self._backplane.attach_queue(
                _PREFIX_MESSAGE + group, self._queue
            )

    async def remove_from_group(self, group: str):
        if group not in self._groups:
            return
        self._groups.remove(group)
        if self._active:
            await self._backplane.detach_queue(
                _PREFIX_MESSAGE + group, self._queue
            )


class ChannelLayer:
    def __init__(self, backplane: BackplaneBase):
        self._backplane = backplane
        self._connections: dict[str, Connection] = {}
        self._id: str = nanoid.generate(size=10)
        self._internal_messages_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def start(self):
        if self._initialized:
            return
        self._initialized = True
        self._internal_messages_task = asyncio.create_task(
            self._internal_messages()
        )

    async def dispose(self):
        if not self._initialized:
            return
        self._initialized = False
        self._internal_messages_task.cancel()
        await self._internal_messages_task

    def _raise_if_not_initialized(self):
        if not self._initialized:
            raise RuntimeError("Channel layer is not initialized yet")

    async def _internal_messages(self):
        try:
            async with self._backplane.subscribe(
                _PREFIX + "actions",
                _PREFIX + "actions/" + self._id,
            ) as sub:
                async for _, message in sub:
                    await self._handle_internal_message(message)
        except asyncio.CancelledError:
            pass

    async def _handle_internal_message(self, message: dict):
        msg_type = message["type"]
        if msg_type == "disconnect_connection":
            connection_id = message.get("connection_id")
            if connection_id in self._connections:
                await self._connections[connection_id].send("disconnect", None)

    if TYPE_CHECKING:

        def new_connection(self) -> AsyncContextManager[Connection]:
            ...

    @asynccontextmanager
    async def new_connection(self) -> Connection:
        self._raise_if_not_initialized()
        connection = Connection(self._backplane)
        self._connections[connection.id] = connection
        try:
            async with connection:
                yield connection
        finally:
            del self._connections[connection.id]

    async def close_group_connections(self, group_name: str):
        await self._groups_send_raw([group_name], {"type": "disconnect"})

    async def close_connection(self, connection_id: str):
        layer_id, connection_id = self._parse_id(connection_id)
        if layer_id == self._id:
            if connection_id in self._connections:
                await self._connections[connection_id].send("disconnect", None)
        else:
            await self._backplane.publish(
                "__internal:" + layer_id,
                {
                    "type": "disconnect_connection",
                    "connection_id": connection_id,
                },
            )

    def group_send(self, group: str, msg_type: str, data: Any = None):
        return self.groups_send([group], msg_type, data)

    async def groups_send(
        self, groups: list[str], msg_type: str, data: Any = None
    ):
        if isinstance(data, BaseModel):
            data = data.dict(by_alias=True)
        await self._groups_send_raw(
            groups,
            {"type": "message", "message": {"type": msg_type, "data": data}},
        )

    async def _groups_send_raw(self, groups: list[str], data: dict):
        if isinstance(data, BaseModel):
            data = data.dict(by_alias=True)
        await self._backplane.publish_many(
            [_PREFIX_MESSAGE + g for g in groups],
            data,
        )

    def _parse_id(self, connection_id: str):
        parts = connection_id.split(".", 1)
        if len(parts) == 1:
            return self._id, parts[0]
        return parts


async def start_channel_layer(app: FastAPI):
    app.state.channel_layer = ChannelLayer(backplane=get_backplane(app))
    await app.state.channel_layer.start()


async def stop_channel_layer(app: FastAPI):
    try:
        channel_layer = get_channel_layer(app)
    except RuntimeError:
        return
    await channel_layer.dispose()


def get_channel_layer(app: FastAPI = Depends(get_application)) -> ChannelLayer:
    try:
        return app.state.channel_layer
    except AttributeError:
        raise RuntimeError(
            f"Channel layer is not initialized on application {app}"
        )
