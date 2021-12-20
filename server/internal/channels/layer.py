import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import timedelta, datetime
from typing import *

import nanoid
from pydantic import BaseModel

from server.internal.channels.backplane import BackplaneBase, get_default_backplane

CHANNEL_LAYER_PREFIX = 'CL'


class HubError(Exception):
    pass


class ConnectionStateError(HubError):
    pass


class HubProxy(ABC):
    @abstractmethod
    def _send(self, msg_type: str, message: Any) -> Awaitable[None]:
        ...

    def send(self, msg_type: str, message: Any):
        if isinstance(message, BaseModel):
            message = message.dict()
        return self._send(msg_type, message)


class Connection(HubProxy):
    def __init__(self, backplane: BackplaneBase):
        self.id = nanoid.generate()
        self._backplane = backplane
        self._queue = asyncio.Queue()
        self.disconnected_at: Optional[datetime] = None
        self._groups = set()
        self._active = False

    async def remove_all_groups(self):
        # TODO проверить на race condition
        if self._active:
            for g in self._groups:
                await self._backplane.detach_listener(CHANNEL_LAYER_PREFIX + g, self._queue.put)
        self._groups.clear()

    async def add_to_group(self, group: str):
        if group in self._groups:
            return
        self._groups.add(group)
        if self._active:
            await self._backplane.attach_listener(CHANNEL_LAYER_PREFIX + group, self._queue.put)

    async def remove_from_group(self, group: str):
        if group not in self._groups:
            return
        self._groups.remove(group)
        if self._active:
            await self._backplane.detach_listener(CHANNEL_LAYER_PREFIX + group, self._queue.put)

    async def __aenter__(self):
        assert not self._active, 'Connection cannot be activated if it\'s already active'
        self._active = True
        for group in self._groups:
            await self._backplane.attach_listener(CHANNEL_LAYER_PREFIX + group, self._queue.put)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        assert self._active, 'Connection cannot be deactivate when it\'s already deactivated'
        self._active = False
        for group in self._groups:
            await self._backplane.detach_listener(CHANNEL_LAYER_PREFIX + group, self._queue.put)

    def _send(self, msg_type: str, message: Any) -> Awaitable[None]:
        return self._queue.put({'msg_type': msg_type, 'data': message})

    async def queued_messages(self) -> AsyncIterable[dict]:
        assert self._active, 'Connection is not active'
        while True:
            message = await self._queue.get()
            if message is None:
                break
            yield message


class ChannelLayer:
    def __init__(self,
                 keep_alive_timeout: timedelta,
                 backplane: BackplaneBase):
        if keep_alive_timeout.total_seconds() == 0:
            raise ValueError("Keep-alive timeout cannot be zero")
        self._backplane = backplane
        self._connections: Dict[str, Connection] = {}
        self._ka_timeout = keep_alive_timeout
        self._id: str = nanoid.generate(size=10)
        self._internal_messages_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def start(self):
        if self._initialized:
            return
        self._initialized = True
        self._internal_messages_task = asyncio.create_task(self._internal_messages())

    async def dispose(self):
        if not self._initialized:
            return
        self._initialized = False
        self._internal_messages_task.cancel()
        await self._internal_messages_task

    def __raise_if_not_initialized(self):
        if not self._initialized:
            raise RuntimeError('Channel layer is not initialized yet')

    async def _internal_messages(self):
        try:
            async with self._backplane.subscribe('__internal', '__internal:' + self._id) as sub:
                async for message in sub:
                    await self._handle_internal_message(message)
        except asyncio.CancelledError:
            pass

    async def _handle_internal_message(self, message: dict):
        print(message)
        data = message['data']
        msg_type = message['msg_type']
        if msg_type == 'disconnect_connection':
            connection_id = data.get('connection_id')
            print('received', connection_id)
            if connection_id in self._connections:
                await self._connections[connection_id].send('__disconnect__', None)

    if TYPE_CHECKING:
        def new_connection(self) -> AsyncContextManager[Connection]:
            ...

    @asynccontextmanager
    async def new_connection(self) -> Connection:
        self.__raise_if_not_initialized()
        connection = Connection(self._backplane)
        self._connections[connection.id] = connection
        try:
            async with connection:
                yield connection
        finally:
            del self._connections[connection.id]

    async def close_connection(self, connection_id: str):
        layer_id, connection_id = self._parse_id(connection_id)
        if layer_id == self._id:
            if connection_id in self._connections:
                await self._connections[connection_id].send('__disconnect__', None)
        else:
            await self._backplane.publish(
                '__internal:' + layer_id,
                {'msg_type': 'disconnect_connection', 'data': {'connection_id': connection_id}})

    def group_send(self, group: str, msg_type: str, data: Any):
        return self.groups_send([group], msg_type, data)

    async def groups_send(self, groups: List[str], msg_type: str, data: Any):
        await self._backplane.publish_many([CHANNEL_LAYER_PREFIX + g for g in groups], {'msg_type': msg_type, 'data': data})

    def _parse_id(self, connection_id: str):
        parts = connection_id.split('.', 1)
        if len(parts) == 1:
            return self._id, parts[0]
        return parts


_channel_layer: Optional[ChannelLayer] = None


def get_channel_layer():
    global _channel_layer
    if _channel_layer is None:
        _channel_layer = ChannelLayer(timedelta(minutes=1), get_default_backplane())
    return _channel_layer
