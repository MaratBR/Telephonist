import base64
import pickle
from contextlib import asynccontextmanager
from typing import Optional, Generic, TypeVar, Any

from broadcaster import Broadcast
from pydantic.generics import GenericModel

from server.settings import settings

T = TypeVar('T')


class BroadcastEvent(GenericModel, Generic[T]):
    channel: str
    data: T
    pattern: Optional[str]


class BroadcastWrapper(Broadcast):
    class SubscriberWrapper:
        def __init__(self, inner):
            self._inner = inner

        async def __aiter__(self):
            async for message in self._inner:
                try:
                    yield decode_broadcast_message(message)
                except ValueError:
                    pass

    async def publish(self, channel: str, message: Any) -> None:
        await super(BroadcastWrapper, self).publish(channel, encode_broadcast_message(message))

    @asynccontextmanager
    async def subscribe(self, channel: str) -> SubscriberWrapper:
        ctx_manager = super(BroadcastWrapper, self).subscribe(channel)
        try:
            async with ctx_manager as sub:
                yield self.SubscriberWrapper(sub)
        finally:
            pass


broadcast = Broadcast(settings.broadcaster_url)


def encode_broadcast_message(data: Any) -> str:
    return base64.b85encode(pickle.dumps(data)).decode('ascii')


def decode_broadcast_message(string: str) -> Any:
    try:
        return pickle.loads(base64.b85decode(string))
    except:
        raise ValueError('Failed to decode broadcast message')
