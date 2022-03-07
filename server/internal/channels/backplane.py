import asyncio
import logging
import pickle
import time
import warnings
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import partial
from typing import *

from aioredis import Redis

_logger = logging.getLogger("telephonist.channels")


def encode_object(data: Any) -> bytes:
    return pickle.dumps(data)


def decode_object(string: bytes) -> Any:
    return pickle.loads(string)


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
        self._channels: dict[str, List[asyncio.Queue]] = {}

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
                    data = decode_object(message["d"])
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
    _logger.debug("starting backplane")
    _backplane = backplane
    await _backplane.start()


async def stop_backplane():
    global _backplane
    _logger.debug("stopping backplane")
    if _backplane:
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
