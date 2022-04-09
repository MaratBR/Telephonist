import asyncio
import logging
import warnings
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from functools import partial
from typing import *

import orjson
from aioredis import Redis
from bson import ObjectId
from pydantic import BaseModel

_logger = logging.getLogger("telephonist.channels")


def _default_serialization(o):
    if isinstance(o, BaseModel):
        return o.dict(by_alias=True)
    if isinstance(o, ObjectId):
        return str(o)
    raise TypeError


def encode_object(data: Any) -> bytes:
    return orjson.dumps(data, default=_default_serialization)


_classes_cache: dict[str, type] = {}


def decode_object(string: bytes) -> Any:
    return orjson.loads(string)


class Subscription:
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    async def __aiter__(self) -> AsyncIterable[Tuple[str, Any]]:
        while True:
            yield await self._queue.get()


Unsubscribe = Callable[[], Awaitable[None]]
BackplaneListener = Callable[[Any], Union[None, Awaitable[None]]]


class BackplaneBase(ABC):
    def __init__(self):
        pass

    @abstractmethod
    async def ping(self):
        ...

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
        for ch in channels:
            await self.attach_queue(ch, queue)

        try:
            yield Subscription(queue)
        finally:
            for ch in channels:
                await self.detach_queue(ch, queue)

    @abstractmethod
    async def attach_queue(self, channel: str, queue: asyncio.Queue):
        ...

    @abstractmethod
    async def detach_queue(self, channel: str, queue: asyncio.Queue):
        ...


class InMemoryBackplane(BackplaneBase):
    # TODO check if something is wrong here, i wrote this without check if it's ok

    def __init__(self):
        super(InMemoryBackplane, self).__init__()
        self._keys = {}
        self._channels: dict[str, List[asyncio.Queue]] = {}

    async def start(self):
        pass

    async def stop(self):
        pass

    async def publish_many(self, channels: List[str], data: Any):
        for channel in channels:
            queues = self._channels.get(channel)
            if queues is None:
                continue
            print(
                f"publishing to {channel}, {len(queues)} queues"
                f' ({", ".join(map(str, map(id, queues)))})'
            )
            for q in queues:
                try:
                    await q.put((channel, data))
                    await asyncio.sleep(0)
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

    async def ping(self):
        pass


class RedisBackplane(BackplaneBase):
    def __init__(self, redis: Redis):
        super(RedisBackplane, self).__init__()
        self._redis = redis
        self._listeners: dict[str, List[asyncio.Queue]] = {}
        self._pubsub = self._redis.pubsub()
        self._receiver_task: Optional[asyncio.Task] = None

    async def stop(self):
        await self._redis.close()
        if self._receiver_task and not self._receiver_task.done():
            self._receiver_task.cancel()
            await self._receiver_task

    async def start(self):
        pass

    async def ping(self):
        await self._redis.ping()

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
                    _logger.exception(f"{exc}, {message}")
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
    _logger.debug("starting backplane")
    _backplane = backplane
    await _backplane.start()


async def stop_backplane():
    global _backplane
    _logger.debug("stopping backplane")
    if _backplane:
        await _backplane.stop()  # noqa
        _backplane = None


def get_backplane() -> BackplaneBase:
    assert _backplane is not None, "backplane is not yet initialized"
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
