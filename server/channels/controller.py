import inspect
from typing import Optional

from fastapi import Depends

from server.channels import ChannelHelper


def broadcast_channel(channel_name: Optional[str] = None):
    def decorator(fn):
        assert inspect.iscoroutinefunction(fn), 'Channel message handler must be an async function'
        setattr(fn, '__channel_name__', channel_name or fn.__name__)
        return fn
    return decorator


def message_handler(channel_name: Optional[str] = None):
    def decorator(fn):
        assert inspect.iscoroutinefunction(fn), 'Message handler must be an async function'
        setattr(fn, '__channel_name__', channel_name or fn.__name__)
        return fn
    return decorator


class ChannelController:
    _initialized: bool
    _channel_handlers: dict
    _message_handlers: dict

    def __init_subclass__(cls, **kwargs):
        cls._initialized = False
        return super(ChannelController, cls).__init_subclass__(**kwargs)

    def __init__(self, helper: ChannelHelper):
        self.helper = helper

    async def initialize(self):
        pass

    async def _run(self):
        self._init()
        await self.helper.accept()
        try:
            await self.initialize()
        except Exception as exc:
            await self._on_exception(exc)
            return
        for key, channel_name in self._channel_handlers.items():
            self.helper.set_channel_handler(channel_name, getattr(self, key))
        self.helper.message(self.on_message)
        self.helper.error(self.on_error)
        await self.helper.start()

    async def on_error(self, exception: Exception):
        await self.helper.close()
        raise exception

    async def on_message(self, msg_type: str, data):
        handler = self._message_handlers.get(msg_type)
        if handler:
            await handler(data)

    @classmethod
    def _init(cls):
        if cls._initialized:
            return
        cls._initialized = True
        cls._channel_handlers = {}
        cls._message_handlers = {}
        for f in dir(cls):
            if f.startswith('__'):
                continue
            v = getattr(cls, f)
            if hasattr(v, '__channel_name__'):
                cls._message_handlers[getattr(v, '__channel_name__')] = f
            elif hasattr(v, '__message_type__'):
                cls._message_handlers[getattr(v, '__message_type__')] = f

    @classmethod
    def as_view(cls):
        async def view(helper: ChannelHelper = Depends()):
            await cls(helper)._run()

        return view

    async def _on_exception(self, exc):
        await self.helper.send_error(exc)
        await self.helper.close()
        raise exc
