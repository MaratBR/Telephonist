import asyncio
import collections
import enum
import json
from json import JSONDecodeError
from typing import Optional, Callable, Any, Awaitable, Union, Type, Dict, OrderedDict

import pydantic.json
from fastapi import Depends
from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from server.auth.utils import bearer
from server.channels.broadcast import broadcast, BroadcastEvent
from server.common.utils import AsyncMerger


class WSEvent(enum.Enum):
    CHANNEL_MESSAGE = 0
    CHANNEL_CLOSED = 1
    MESSAGE = 2
    MESSAGE_ERROR = 3
    CLOSING = -1


class ChannelHelper:
    _events: Optional[AsyncMerger]
    _message_converter: Optional[Callable[[Any], Any]]

    def __init__(self, websocket: WebSocket, token: Optional[str] = Depends(bearer)):
        self._ws = websocket
        self._initialized = False
        self._events = None
        self.token = token
        self._message_converter = None
        self._fallback_channel_handler = None

        self._subscription_tasks_ids = {}
        self._channel_handlers: Dict[str, Callable[[Any], Awaitable]] = {}
        self._glob_patterns: OrderedDict[str, Callable[[Any], Awaitable]] = collections.OrderedDict()
        self._subscribed = set()
        self._scheduled_psubscribe = set()
        self._scheduled_subscribe = set()

    async def _ensure_init(self):
        if not self._initialized:
            self._initialized = True
            await self.init()

    def message(self, handler_fn: Callable[[str, Any], Awaitable]):
        self._on_message = handler_fn

    def error(self, handler: Callable[[Exception], Awaitable]):
        self._on_exception = handler

    def channel(self, name: str, *, glob: bool = True):
        def decorator(fn):
            self.subscribe(name, fn, glob=glob)
            return fn

        return decorator

    def fallback_channel(self, handler: Callable[[str, Any], Awaitable]):
        self._fallback_channel_handler = handler

    def set_channel_handler(self, name: str, fn: Callable[[Any], Awaitable], glob: bool = False):
        if glob:
            self._glob_patterns[name] = fn
        else:
            self._channel_handlers[name] = fn

    @staticmethod
    async def _on_message(_name, _data):
        pass

    async def _on_exception(self, exception):
        await self._ws.close(1011)

    async def _subscribe(self, name: str, glob: bool = False):
        assert self._initialized, 'helper is not initialized yet!'

        async def _drain():
            sub_with = broadcast.psubscribe(name) if glob else broadcast.subscribe(name)
            async with sub_with as sub:
                async for event in sub:
                    yield WSEvent.CHANNEL_MESSAGE, event
            yield WSEvent.CHANNEL_CLOSED, name

        self._events.add(_drain(), 'channel:' + name)

    async def subscribe(self, channel: str, fn: Callable[[BroadcastEvent], Awaitable], *, glob: bool = False):
        if channel in self._subscribed:
            return
        if glob:
            self._glob_patterns[channel] = fn
        else:
            self._channel_handlers[channel] = fn
        if self._initialized:
            self._subscribed.add(channel)
            await self._subscribe(channel, glob=glob)
        else:
            if glob:
                self._scheduled_psubscribe.add(channel)
            else:
                self._scheduled_subscribe.add(channel)

    async def unsubscribe(self, channel: str):
        if channel not in self._subscribed:
            return
        self._subscribed.remove(channel)

        if channel in self._channel_handlers:
            del self._channel_handlers[channel]
        elif channel in self._glob_patterns:
            del self._glob_patterns[channel]

        self._events.remove('channel:' + channel)

    async def init(self):
        self._events = AsyncMerger(asyncio.Queue(1))
        tasks = [
            self._subscribe(channel)
            for channel in self._scheduled_subscribe
        ]
        tasks += [
            self._subscribe(pattern, glob=True)
            for pattern in self._scheduled_psubscribe
        ]
        self._subscribed = {*self._scheduled_subscribe, *self._scheduled_psubscribe}
        self._scheduled_subscribe.clear()
        self._scheduled_psubscribe.clear()
        await asyncio.gather(*tasks)

    async def receive(self, pipe: Union[Callable[[Any], Any], Type[BaseModel]]):
        if issubclass(pipe, BaseModel):
            def pipe_fn(data):
                try:
                    return pipe(**data)
                except ValidationError:
                    return None
        else:
            pipe_fn = pipe

        data = None
        while data is None:
            try:
                data = await self._ws.receive_json()
            except JSONDecodeError:
                continue
            data = pipe_fn(data)
        return data

    async def start(self):
        await self._ensure_init()
        self._start_receiving_messages()

        async for event in self._events:
            try:
                if await self._handle_event(event):
                    break
            except Exception as exc:
                await self._on_exception(exc)
        self._stop()

    async def _handle_event(self, event):
        if event[0] == WSEvent.CHANNEL_MESSAGE:
            # сообщение из канала
            event_obj: BroadcastEvent = event[1]
            if event_obj.pattern and event_obj.pattern in self._glob_patterns:
                handler = self._glob_patterns[event_obj.pattern]
            elif event_obj.pattern is None and event_obj.channel in self._channel_handlers:
                handler = self._channel_handlers[event_obj.channel]
            else:
                handler = self._fallback_channel_handler

            if handler:
                try:
                    await handler(event_obj)
                except Exception as exc:
                    await self._on_exception(exc)
        elif event[0] == WSEvent.MESSAGE:
            # обычное сообщение от клиента
            data = event[1]
            if isinstance(data, list) and len(data) == 2 and isinstance(data[0], str):
                msg_type, data = data
                if self._message_converter:
                    data = self._message_converter(data)
                await self._on_message(msg_type, data)
            else:
                return
        elif event[0] == WSEvent.CLOSING:
            # stop
            return True

    def _start_receiving_messages(self):
        async def _receive():
            try:
                while True:
                    try:
                        message = await self._ws.receive_json()
                    except JSONDecodeError as exc:
                        yield WSEvent.MESSAGE_ERROR, exc
                        continue
                    yield WSEvent.MESSAGE, message
            except WebSocketDisconnect:
                print('WebSocketDisconnect')
            except Exception as e:
                print(e)
            finally:
                yield WSEvent.CLOSING,

        self._events.add(_receive(), 'receiver_task')

    async def send_channel(self, channel, data):
        await broadcast.publish(channel, data)

    async def send(self, data: Any):
        if isinstance(data, BaseModel):
            await self._ws.send_text(data=data.json())
        else:
            await self._ws.send_json(data)

    async def send_message(self, msg_type: str, data: Optional[Any] = None):
        if isinstance(data, BaseModel):
            # симулируем сериализацию в JSON, потому что pydantic использует
            # свой сериализатор, если просто использовать тут json.dumps не получится
            # вот это не будет работать: await self.send([msg_type, data.dict()])
            await self._ws.send_text(f'[{json.dumps(msg_type)}, {data.json()}]')
        else:
            await self.send([msg_type, data])

    async def send_error(self, error: Any):
        await self.send_message('error', error)

    def set_message_pipe(
            self,
            pipe: Union[Callable[[Any], Any], Type[BaseModel]]
    ):
        if issubclass(pipe, BaseModel):
            def _function(data: Any) -> pipe:
                if not isinstance(data, dict):
                    raise TypeError()
                try:
                    return pipe(**data)
                except ValidationError:
                    raise TypeError()

            self._message_converter = _function
        else:
            self._message_converter = pipe

    def _stop(self):
        self._events.stop()
