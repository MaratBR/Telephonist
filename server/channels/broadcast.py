import asyncio
import base64
import fnmatch
import json
import logging
import pickle
from contextlib import asynccontextmanager
from typing import Optional, Dict, Set, AsyncIterable, Any, AsyncContextManager, List

import aioredis
from pydantic import BaseModel

from server.settings import settings


class BroadcastEvent(BaseModel):
    channel: str
    data: Any
    pattern: Optional[str]


class Subscription:
    def __init__(self, queue: asyncio.Queue):
        self._q = queue

    async def __aiter__(self) -> AsyncIterable[BroadcastEvent]:
        while True:
            item = await self._q.get()
            if item is None:
                break
            yield item


class Broadcast:
    logger = logging.getLogger('Broadcast')
    __logger_handler = logging.StreamHandler()
    __logger_handler.setFormatter(logging.Formatter('%(levelname)s|%(name)s|%(asctime)s|%(message)s'))
    logger.addHandler(__logger_handler)
    logger.setLevel(logging.DEBUG)
    del __logger_handler

    def __init__(self, redis_url: Optional[str]):
        self._url = redis_url
        self._subscribed = set()
        self._pub: Optional[aioredis.Redis] = None
        self._sub: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._ready = False
        self._queues: Dict[str, Set[asyncio.Queue[Any]]] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._in_memory_queue: Optional[asyncio.Queue] = None
        self._glob_patterns: Optional[Set[str]] = None

        self._logger = self.logger.getChild('memory' if self.is_memory else 'redis')

    async def publish(self, channel: str, data: Any = None):
        self._logger.debug(f'publish {data} > {channel}')
        if self.is_memory:
            await self._in_memory_queue.put(BroadcastEvent(channel=channel, data=data))
        else:
            converted = self._encode_message(data)
            await self._pub.publish(channel, converted)

    async def publish_many(self, channels: List[str], data: Any):
        self._logger.debug(f'publish many {data} > {channels}')
        if self.is_memory:
            await asyncio.gather(*(
                self._in_memory_queue.put(BroadcastEvent(channel=channel, data=data))
                for channel in channels
            ))
        else:
            converted = self._encode_message(data)
            await asyncio.gather(*(
                self._pub.publish(channel, converted)
                for channel in channels
            ))

    async def connect(self):
        if self._ready:
            return

        self._ready = True
        if not self.is_memory:
            self._pub = aioredis.from_url(self._url, max_connections=10, decode_responses=True)
            self._sub = aioredis.from_url(self._url, max_connections=10, decode_responses=True)
            self._pubsub = self._sub.pubsub()
            self._ensure_listener()
        else:
            self._in_memory_queue = asyncio.Queue()
            self._glob_patterns = set()

    async def disconnect(self):
        self._ready = False
        if not self.is_memory:
            await self._pubsub.close()
            await self._sub.close()
            await self._pub.close()
            if self._listener_task and not self._listener_task.done():
                await self._listener_task

            self._sub = None
            self._pub = None
            self._pubsub = None
        else:
            await self._in_memory_queue.put(None)

    @property
    def is_memory(self) -> bool:
        return self._url is None

    @asynccontextmanager
    async def _subscribe(self, channel: str, glob: bool = False) -> Subscription:
        queue = asyncio.Queue()

        try:
            self._subscribed.add(channel)
            if channel in self._queues:
                self._queues[channel].add(queue)
            else:
                self._queues[channel] = {queue}

            if self.is_memory:
                if glob:
                    self._glob_patterns.add(channel)
            else:
                if glob:
                    await self._pubsub.psubscribe(channel)
                else:
                    await self._pubsub.subscribe(channel)

            subscription = Subscription(queue)
            self._ensure_listener()

            yield subscription
        finally:
            if self.is_memory:
                if glob:
                    self._glob_patterns.remove(channel)
            else:
                if glob:
                    await self._pubsub.unsubscribe(channel)
                else:
                    await self._pubsub.punsubscribe(channel)
            await queue.put(None)
            self._subscribed.remove(channel)
            self._queues[channel].remove(queue)

    def subscribe(self, channel: str) -> AsyncContextManager[Subscription]:
        return self._subscribe(channel)

    def psubscribe(self, channel: str) -> AsyncContextManager[Subscription]:
        return self._subscribe(channel, glob=True)

    def _ensure_listener(self):
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._listener())

    async def _listener(self):
        self._logger.debug('running listener')
        if self.is_memory:
            while True:
                event: Optional[BroadcastEvent] = await self._in_memory_queue.get()
                if event is None:
                    break
                tasks = []
                queues = self._queues.get(event.channel)
                if queues:
                    for q in queues:
                        tasks.append(q.put(event))
                for pattern in self._glob_patterns:
                    if fnmatch.fnmatch(event.channel, pattern):
                        queues = self._queues.get(pattern)
                        for q in queues:
                            tasks.append(q.put(BroadcastEvent(channel=event.channel, data=event.data, pattern=pattern)))
                await asyncio.gather(*tasks)
                await asyncio.sleep(.01)
        else:
            await self._pubsub.ping()
            while self._pubsub.connection is not None:
                try:
                    message = await self._pubsub.get_message(ignore_subscribe_messages=True)
                    if message is not None:
                        msg_type = message['type']
                        if msg_type not in ('message', 'pmessage'):
                            continue
                        data = self._decode_message(message['data'])
                        event = BroadcastEvent(channel=message['channel'], data=data, pattern=message['pattern'])
                        queue_name = message['channel'] if msg_type == 'message' else message['pattern']
                        queues = self._queues.get(queue_name)
                        if queues:
                            await asyncio.gather(*(
                                q.put(event)
                                for q in queues
                            ))
                except Exception as exc:
                    self._logger.exception(exc)
                await asyncio.sleep(.01)
        self._logger.debug('listener: exiting')

    @staticmethod
    def _encode_message(data):
        if data is None:
            return ''
        if isinstance(data, str):
            data = 'S:' + data
        else:
            data = 'PICKLE85:' + base64.b85encode(pickle.dumps(data)).decode('ascii')
        return data

    @staticmethod
    def _decode_message(message: str):
        if message == '':
            return None
        encoding_type, text = message.split(':', maxsplit=1)
        encoding_type = encoding_type.upper()
        if encoding_type == 'PICKLE85':
            return pickle.loads(base64.b85decode(text))
        elif encoding_type == 'JSON':
            return json.loads(text)
        elif encoding_type == 'S':
            return text


broadcast = Broadcast(None if settings.use_local_messaging else settings.redis_url)
