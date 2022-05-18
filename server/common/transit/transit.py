import asyncio
import dataclasses
import inspect
import logging
import warnings
from abc import abstractmethod
from typing import Optional, TypeVar, Union, get_args, get_origin

_logger = logging.getLogger("telephonist.transit")


class Handler:
    @abstractmethod
    async def handle_message(self, message):
        ...

    async def enable(self):
        ...

    async def disable(self):
        ...


class BatchHandler(Handler):
    def __init__(self, original_handler: Handler, delay: float, max_size: int):
        self.logger = logging.getLogger("telephonist.transit")
        self._pile = []
        self._staged_piles = asyncio.Queue()
        self.delay = delay
        self.max_size = max_size
        self.original_handler = original_handler
        self._wake_up = asyncio.Event()
        self._loop_task = None
        self._delay_loop_task: Optional[asyncio.Task] = None
        self._ready = False
        self._enabled = True

    async def handle_message(self, message):
        self._ensure_tasks()
        self._pile.append(message)
        if len(self._pile) == 1:
            self._wake_up.set()
        if len(self._pile) >= self.max_size:
            pile = self._pile
            self._pile = []
            await self._staged_piles.put(pile)

    async def on_failure(self, exc: Exception):
        self.logger.error(
            f"{type(self).__name__} failed to process messages batch: {exc}"
        )

    async def disable(self):
        if self._delay_loop_task and not self._delay_loop_task.done():
            self._delay_loop_task.cancel()
            await self._delay_loop_task
        self._enabled = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            await self._loop_task

    async def _delay_loop(self):
        try:
            while True:
                await self._wake_up.wait()
                self._wake_up.clear()
                await asyncio.sleep(self.delay)
                if len(self._pile) == 0:
                    continue
                pile = self._pile
                self._pile = []
                await self._staged_piles.put(pile)
        except asyncio.CancelledError:
            if len(self._pile) > 0:
                await self._staged_piles.put(self._pile)

    async def _loop(self):
        async def handle_pile():
            pile = await self._staged_piles.get()
            try:
                await self.original_handler.handle_message(pile)
            except Exception as exc:
                asyncio.create_task(self.on_failure(exc))

        try:
            while True:
                await handle_pile()
        except asyncio.CancelledError:
            while not self._staged_piles.empty():
                await handle_pile()

    def _ensure_tasks(self):
        if self._delay_loop_task is None:
            self._delay_loop_task = asyncio.create_task(self._delay_loop())
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._loop())


class FunctionHandler(Handler):
    def __init__(self, function):
        self.function = function

    async def handle_message(self, message):
        return await self.function(message)


@dataclasses.dataclass
class BatchConfig:
    max_batch_size: int
    delay: float


class TransitEndpointBase:
    def __init__(self):
        self._handlers: dict[str, list[Handler]] = {}
        self._enabled_handlers = set()
        self._logger = logging.getLogger("telephonist.transit")
        self._error_logger = self._logger.getChild("error")
        self._object_handlers = {}

    @staticmethod
    def infer_message_type_from_signature(fun):
        parameters = list(inspect.signature(fun).parameters.values())
        required = [
            p for p in parameters if p.default is inspect.Parameter.empty
        ]
        if len(required) != 1:
            raise ValueError(
                "invalid event handler function signature, function must have"
                " exactly 1 required parameter"
            )
        annotation = parameters[0].annotation
        if annotation is inspect.Parameter.empty:
            raise ValueError(
                "invalid event handler function signature, parameter's"
                " annotation is empty"
            )
        if not isinstance(annotation, type):
            raise ValueError(
                "invalid event handler function signature, function must have"
                " 1 required parameter annotated with type of the event"
            )
        return annotation

    @staticmethod
    def infer_handlers(o) -> list[tuple[Union[str, type], Handler]]:
        if inspect.isfunction(o) or inspect.ismethod(o):
            assert inspect.iscoroutinefunction(o), (
                "You can only register coroutine functions, not synchronous"
                " ones"
            )
            metadata = getattr(o, "__transit_handler__", {})
            message_type: Optional[Union[str, type]] = metadata.get(
                "message_type"
            )
            if message_type is None:
                # infer message type from function signature
                message_type = (
                    message_type_t
                ) = TransitEndpointBase.infer_message_type_from_signature(o)
            elif isinstance(message_type, type):
                message_type_t = message_type
                try:
                    inferred_type = (
                        TransitEndpointBase.infer_message_type_from_signature(
                            o
                        )
                    )
                    if not issubclass(message_type, inferred_type):
                        warnings.warn(
                            f"Inferred type of the event for function {o} is"
                            " not the same as the supplied one, please check"
                            " function signature"
                        )
                except ValueError:
                    pass
            else:
                message_type_t = None

            batch: Optional[BatchConfig] = metadata.get("batch")
            handler = FunctionHandler(o)
            if batch:
                assert message_type_t, (
                    "Handler signature must have a type annotation set if you"
                    " want to use BatchConfig"
                )
                assert get_origin(message_type_t) is list, (
                    "Handler with BatchConfig set must accept list of events"
                    " (i.e. List[T] or list[T], not T)."
                    f" message_type_t={message_type_t}"
                )
                (message_type_t,) = get_args(message_type_t)
                message_type = message_type_t
                assert isinstance(
                    message_type_t, type
                ), "Parameter of generic list[T] (or List[T]) must be a type!"
                handler = BatchHandler(
                    handler, batch.delay, batch.max_batch_size
                )

            return [(message_type, handler)]

        else:
            methods = inspect.getmembers(
                o,
                lambda m: inspect.ismethod(m)
                and hasattr(m, "__transit_handler__"),
            )
            handlers = []
            for _, method in methods:
                handlers += TransitEndpointBase.infer_handlers(method)
            return handlers

    def add_handler(self, message_type: Union[str, type], handler: Handler):
        if isinstance(message_type, type):
            message_type_str = f"TYPED<{message_type.__name__}>"
        else:
            message_type_str = message_type
        handlers = self._handlers.get(message_type_str)
        if handlers:
            if handler in handlers:
                return
            handlers.append(handler)
        else:
            self._handlers[message_type_str] = [handler]

    def remove_handler(self, message_type: Union[str, type], handler: Handler):
        if isinstance(message_type, type):
            message_type_str = f"TYPED<{message_type.__name__}>"
        else:
            message_type_str = message_type

        handlers = self._handlers.get(message_type_str)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def register(self, o) -> list[Handler]:
        handlers = TransitEndpointBase.infer_handlers(o)
        if len(handlers) > 0:
            _logger.debug(f"registering handlers for {o}")
            for message_type, handler in handlers:
                _logger.debug(
                    f"\tregistering {handler} for message type {message_type}"
                )
                self.add_handler(message_type, handler)
            self._object_handlers[o] = handlers
            return [p[1] for p in handlers]
        else:
            return []

    def unregister(self, o):
        handlers = self._object_handlers.get(o)
        if handlers:
            for message_type, handler in handlers:
                self.remove_handler(message_type, handler)

            del self._object_handlers[o]

    def unregister_all_of_type(self, type_: type):
        all_objects = [
            o for o in self._object_handlers.keys() if type(o) is type_
        ]
        for o in all_objects:
            self.unregister(o)

    async def dispatch_message(self, message_type: str, message):
        handlers = self._handlers.get(message_type)
        if handlers is None:
            return
        for handler in handlers:
            if handler not in self._enabled_handlers:
                self._enabled_handlers.add(handler)
                await handler.enable()
            try:
                await handler.handle_message(message)
            except Exception as exc:
                self._error_logger.error(str(exc))

    async def shutdown(self):
        self._handlers = {}
        for h in self._enabled_handlers:
            await h.disable()

    async def dispatch(self, message):
        type_ = type(message)
        await self.dispatch_message(f"TYPED<{type_.__name__}>", message)


TEndpoint = TypeVar("TEndpoint", bound=TransitEndpointBase)


def mark_handler(batch: Optional[BatchConfig] = None):
    def decorator(o):
        setattr(o, "__transit_handler__", {"batch": batch})
        return o

    return decorator


class TransitEndpoint(TransitEndpointBase):
    pass
