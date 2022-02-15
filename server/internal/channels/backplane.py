import asyncio
import importlib
import logging
import struct
import time
import warnings
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import *
from uuid import UUID

import msgpack
from aioredis import Redis
from beanie import PydanticObjectId
from pydantic import BaseModel

_MAX32INT = 4294967295
_logger = logging.getLogger("telephonist.channels")


def _default_encoder(o: Any) -> Any:
    # we use pydantic's AppBaseModel rather than telephonist's AppBaseModel
    # here because we want to check for both models and documents
    if isinstance(o, BaseModel):
        model_class = type(o)
        return {
            "__pydantic__": model_class.__module__
            + ":"
            + model_class.__qualname__,
            "_": o.dict(by_alias=True),
        }
    elif isinstance(o, datetime):
        if o.tzinfo:
            offset = int(o.tzinfo.utcoffset(o).total_seconds())
        else:
            offset = _MAX32INT
        return msgpack.ExtType(53, struct.pack("!dI", o.timestamp(), offset))
    elif isinstance(o, PydanticObjectId):
        return msgpack.ExtType(54, o.binary)
    elif isinstance(o, UUID):
        return msgpack.ExtType(55, o.bytes)
    return o


_modules_cache = {}


def _object_hook(obj: dict):
    if "__pydantic__" in obj:
        module, qualname = obj["__pydantic__"].split(":", 1)
        if module not in _modules_cache:
            _modules_cache[module] = importlib.import_module(module)
        model_class = _modules_cache[module]
        parts = qualname.split(".")
        for p in parts:
            model_class = getattr(model_class, p)
        return model_class(**obj["_"])
    return obj


def _ext_hook(code: int, data: Any):
    if code == 54:
        return PydanticObjectId(data)
    elif code == 53:
        ts, offset = struct.unpack("!dI", data)
        return datetime.fromtimestamp(
            ts,
            timezone(timedelta(seconds=offset))
            if offset != _MAX32INT
            else None,
        )
    elif code == 55:
        return UUID(bytes=data)
    return msgpack.ExtType(code, data)


def encode_object(data: Any) -> bytes:
    return msgpack.packb(data, default=_default_encoder)


def decode_object(string: bytes) -> Any:
    return msgpack.unpackb(
        string, ext_hook=_ext_hook, object_hook=_object_hook
    )


class Subscription:
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    async def __aiter__(self) -> AsyncIterable[Tuple[str, Any]]:
        while True:
            yield await self._queue.get()


Unsubscribe = Callable[[], Awaitable[None]]
BackplaneListener = Callable[[Any], Union[None, Awaitable[None]]]


class BackplaneBase(ABC):
    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...

    def publish(self, channel: str, data: Any):
        return self.publish_many([channel], data)

    @abstractmethod
    async def publish_many(self, channels: List[str], data: Any):
        ...

    if TYPE_CHECKING:

        def subscribe(
            self, channel: str, *channels: str
        ) -> AsyncContextManager[AsyncIterable[Tuple[str, Any]]]:
            ...

    @asynccontextmanager
    async def subscribe(self, channel: str, *channels):
        channels = channels + (channel,)

        queue = asyncio.Queue()
        for channel in channels:
            await self.attach_queue(channel, queue)

        try:
            yield Subscription(queue)
        finally:
            for channel in channels:
                await self.detach_queue(channel, queue)

    @abstractmethod
    async def attach_queue(self, channel: str, queue: asyncio.Queue):
        ...

    @abstractmethod
    async def detach_queue(self, channel: str, queue: asyncio.Queue):
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[timedelta] = None):
        ...

    @abstractmethod
    async def get(self, key: str) -> Any:
        ...


class InMemoryBackplane(BackplaneBase):
    # TODO check if something is wrong here, i wrote this without check if it's ok

    def __init__(self):
        self._keys = {}
        self._channels: Dict[str, List[asyncio.Queue]] = {}

    async def start(self):
        pass

    async def stop(self):
        pass

    async def publish_many(self, channels: List[str], data: Any):
        for channel in channels:
            queues = self._channels[channel]
            for q in queues:
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    warnings.warn(
                        "InMemoryBackplane failed to put a message to the"
                        " queue: the queue is full! Channel name is"
                        f' "{channel}"'
                    )

    async def attach_queue(self, channel: str, queue: asyncio.Queue):
        if channel in self._channels:
            if queue not in self._channels[channel]:
                self._channels[channel].append(queue)
        else:
            self._channels[channel] = [queue]

    async def detach_queue(self, channel: str, queue: asyncio.Queue):
        if channel in self._channels and queue in self._channels[channel]:
            self._channels[channel].remove(queue)

    async def set(self, key: str, value: Any, ttl: Optional[timedelta] = None):
        self._keys[key] = {
            "value": value,
            "ttl": ttl,
            "expires_at": datetime.now() + ttl,
        }

    async def get(self, key: str) -> Any:
        entry = self._keys.get(key)
        if entry and entry["expires_at"] > datetime.now():
            return entry["value"]
        elif entry:
            del self._keys[key]


class RedisBackplane(BackplaneBase):
    async def set(self, key: str, value: Any, ttl: Optional[timedelta] = None):
        await self._redis.set(
            key,
            encode_object(
                {
                    "value": value,
                    "created_at": time.time(),
                    "ttl": None if ttl is None else ttl.total_seconds(),
                }
            ),
        )

    async def get(self, key: str) -> Any:
        value = await self._redis.get(key)
        if value is None:
            return None
        try:
            value = decode_object(value)
            if (
                value["ttl"]
                and value["created_at"] + value["ttl"] < time.time()
            ):
                value = None
        except:
            return None
        return value

    def __init__(self, redis: Redis):
        self._redis = redis
        self._listeners: Dict[str, List[asyncio.Queue]] = {}
        self._pubsub = self._redis.pubsub()
        self._receiver_task: Optional[asyncio.Task] = None

    async def stop(self):
        await self._redis.close()
        if self._receiver_task and not self._receiver_task.done():
            self._receiver_task.cancel()
            await self._receiver_task

    async def start(self):
        pass

    async def publish_many(self, channels: List[str], data: Any):
        encoded = encode_object(data)
        tasks = [self._redis.publish(c, encoded) for c in channels]
        await asyncio.gather(*tasks)

    async def _receiver_loop(self):
        try:
            async for message in self._pubsub.listen():
                if message is None or message["type"] != "message":
                    continue
                try:
                    data = decode_object(message["data"])
                except Exception as exc:
                    _logger.exception(str(exc))
                    continue  # TODO

                await self._dispatch_message(message["channel"].decode(), data)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _logger.exception(str(exc))
        _logger.debug("Receiver loop has completed execution")

    async def attach_queue(
        self, channel: str, queue: asyncio.Queue
    ) -> Unsubscribe:
        listeners = self._listeners.get(channel)
        if listeners:
            listeners.append(queue)
        else:
            await self._subscribe(channel)
            self._listeners[channel] = [queue]
        return partial(self.detach_queue, channel, queue)

    async def detach_queue(self, channel: str, queue: asyncio.Queue):
        listeners = self._listeners.get(channel)
        if listeners and queue in listeners:
            listeners.remove(queue)
            if len(listeners) == 0:
                del self._listeners[channel]
                await self._unsubscribe(channel)

    async def _dispatch_message(self, channel: str, message: Any):
        if channel not in self._listeners:
            return
        listeners = [*self._listeners[channel]]
        for listener in listeners:
            await listener.put((channel, message))

    async def _subscribe(self, channel: str):
        await self._pubsub.subscribe(channel)
        if self._receiver_task is None or self._receiver_task.done():
            self._receiver_task = asyncio.create_task(self._receiver_loop())

    async def _unsubscribe(self, channel: str):
        await self._pubsub.unsubscribe(channel)


_backplane: Optional[BackplaneBase] = None


async def start_backplane(backplane: BackplaneBase):
    global _backplane
    assert _backplane is None, "You can't initialize backplane twice"
    _backplane = backplane
    await _backplane.start()


async def stop_backplane():
    global _backplane
    await _backplane.stop()  # noqa
    _backplane = None


def get_default_backplane():
    assert _backplane is not None, "RedisBackplane is not yet initialized"
    return _backplane


T = TypeVar("T")


@asynccontextmanager
async def mapped_subscription(
    manager: AsyncContextManager[AsyncIterable[T]],
    map_function: Callable[[T], T],
) -> AsyncContextManager[AsyncIterable[Tuple[str, Any]]]:
    async with manager as iterable:

        async def mapper():
            async for item in iterable:
                yield map_function(item)

        yield mapper()
