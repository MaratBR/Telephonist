import asyncio
import base64
import inspect
import pickle
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import *

import aioredis
from loguru import logger


def encode_broadcast_message(data: Any) -> str:
    return base64.b85encode(pickle.dumps(data)).decode("ascii")


def decode_broadcast_message(string: str) -> Any:
    try:
        return pickle.loads(base64.b85decode(string))
    except:
        raise ValueError("Failed to decode broadcast message")


class Subscription:
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    async def __aiter__(self):
        while True:
            yield await self._queue.get()


BackplaneListener = Callable[[Any], Union[None, Awaitable[None]]]


class BackplaneBase(ABC):
    def publish(self, channel: str, data: Any):
        return self.publish_many([channel], data)

    @abstractmethod
    async def publish_many(self, channels: List[str], data: Any):
        ...

    @abstractmethod
    def subscribe(self, channel: str, *channels: str) -> AsyncContextManager[AsyncIterable[Any]]:
        ...

    @abstractmethod
    async def attach_listener(self, channel: str, listener: BackplaneListener):
        ...

    @abstractmethod
    async def detach_listener(self, channel: str, listener: BackplaneListener):
        ...


class Backplane(BackplaneBase):
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url)
        self._listeners: Dict[str, List[BackplaneListener]] = {}
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
        encoded = encode_broadcast_message(data)
        tasks = [self._redis.publish(c, encoded) for c in channels]
        await asyncio.gather(*tasks)

    async def _receiver_loop(self):
        try:
            async for message in self._pubsub.listen():
                if message is None or message["type"] != "message":
                    continue
                try:
                    data = decode_broadcast_message(message["data"])
                except Exception as exc:
                    continue  # TODO

                await self._dispatch_message(message["channel"].decode(), data)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception(exc)
        logger.debug("Receiver loop has completed execution")

    @asynccontextmanager
    async def subscribe(self, channel: str, *channels):
        channels = channels + (channel,)

        queue = asyncio.Queue()
        for channel in channels:
            await self.attach_listener(channel, queue.put)

        try:
            yield Subscription(queue)
        finally:
            for channel in channels:
                await self.detach_listener(channel, queue.put)

    async def attach_listener(self, channel: str, listener: BackplaneListener):
        listeners = self._listeners.get(channel)
        if listeners:
            listeners.append(listener)
        else:
            await self._subscribe(channel)
            self._listeners[channel] = [listener]

    async def detach_listener(self, channel: str, listener: BackplaneListener):
        listeners = self._listeners.get(channel)
        if listeners and listener in listeners:
            listeners.remove(listener)
            if len(listeners) == 0:
                del self._listeners[channel]
                await self._unsubscribe(channel)

    async def _dispatch_message(self, channel: str, message: Any):
        if channel not in self._listeners:
            return
        listeners = [*self._listeners[channel]]
        for listener in listeners:
            try:
                v = listener(message)
                if inspect.isawaitable(v):
                    await v
            except Exception as exc:
                logger.exception(exc)

    async def _subscribe(self, channel: str):
        await self._pubsub.subscribe(channel)
        if self._receiver_task is None or self._receiver_task.done():
            self._receiver_task = asyncio.create_task(self._receiver_loop())

    async def _unsubscribe(self, channel: str):
        await self._pubsub.unsubscribe(channel)


_backplane: Optional[Backplane] = None


async def start_backplane(redis_url: str):
    global _backplane
    assert _backplane is None, "You can't initialize backplane twice"
    _backplane = Backplane(redis_url)
    await _backplane.start()


async def stop_backplane():
    global _backplane
    await _backplane.stop()  # noqa
    _backplane = None


def get_default_backplane():
    assert _backplane is not None, "Backplane is not yet initialized"
    return _backplane
