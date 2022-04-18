import asyncio
import dataclasses
import inspect
import logging
import warnings
from abc import abstractmethod
from typing import Optional, Tuple, TypeVar, Union, get_args, get_origin


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


class TransitEndpointBase:
    def __init__(self):
        self._handlers = {}
        self._enabled_handlers = set()
        self._logger = logging.getLogger("telephonist.transit")
        self._error_logger = self._logger.getChild("error")

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


@dataclasses.dataclass
class BatchConfig:
    max_batch_size: int
    delay: float


class EndpointExtensions:
    def register(self: TEndpoint, o=None, batch: Optional[BatchConfig] = None):
        if o is None:

            def decorator(decorated_o):
                self.register(decorated_o, batch=batch)
                return decorated_o

            return decorator

        message_type, handler = EndpointExtensions.infer_handler(o)
        if batch:
            if isinstance(message_type, type):
                if get_origin(message_type) is not list:
                    raise ValueError(
                        "invalid inferred message type: batched event handlers"
                        " require list[T] or typing.List[T]"
                    )
            handler = BatchHandler(
                handler, delay=batch.delay, max_size=batch.max_batch_size
            )
            (message_type,) = get_args(message_type)
        self.add_handler(message_type, handler)

    @staticmethod
    def infer_handler(
        o, message_type: Optional[Union[str, type]] = None
    ) -> Tuple[Union[str, type], Handler]:
        if inspect.isfunction(o):
            assert inspect.iscoroutinefunction(o), (
                "You can only register coroutine functions, not synchronous"
                " ones"
            )
            if message_type is None:
                # infer message type from function signature
                message_type = (
                    EndpointExtensions.infer_message_type_from_signature(o)
                )
            elif isinstance(message_type, type):
                try:
                    inferred_type = (
                        EndpointExtensions.infer_message_type_from_signature(o)
                    )
                    if not issubclass(message_type, inferred_type):
                        warnings.warn(
                            f"Inferred type of the event for function {o} is"
                            " not the same as the supplied one, please check"
                            " function signature"
                        )
                except ValueError:
                    pass
            return message_type, FunctionHandler(o)
        raise TypeError(
            "invalid object for registration in event bus, cannot infer"
            " handler type"
        )

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


class TransitEndpoint(TransitEndpointBase, EndpointExtensions):
    pass
