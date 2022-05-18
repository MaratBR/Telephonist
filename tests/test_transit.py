import asyncio
import contextlib

import pytest

from server.common.transit.transit import (
    BatchConfig,
    TransitEndpoint,
    mark_handler,
)


@contextlib.asynccontextmanager
async def transit():
    t = TransitEndpoint()
    try:
        yield t
    finally:
        await t.shutdown()


@pytest.mark.asyncio
async def test_simple_transit():
    received = False
    async with transit() as t:

        @t.register
        @mark_handler()
        async def handler(message: int):
            assert message == 42
            nonlocal received
            received = True

        await t.dispatch(42)
        await asyncio.sleep(0.5)
        assert received


@pytest.mark.asyncio
async def test_batch_transit():
    count = 10
    received = None
    async with transit() as t:

        @t.register
        @mark_handler(batch=BatchConfig(max_batch_size=count, delay=0.5))
        async def handle(batch: list[int]):
            nonlocal received
            received = len(batch)

        for i in range(5):
            await t.dispatch(42)
        await asyncio.sleep(0.5)
        assert received is None
        await asyncio.sleep(1)
        assert received == 5


@pytest.mark.asyncio
async def test_batch_cap():
    count = 10
    received = None

    async with transit() as t:

        @t.register
        @mark_handler(batch=BatchConfig(max_batch_size=count, delay=1))
        async def handle(batch: list[int]):
            nonlocal received
            received = len(batch)

        for i in range(count + count // 2):
            await t.dispatch(42)
        await asyncio.sleep(0.05)
        assert received == count
        received = None
        await asyncio.sleep(0.9)
        assert received is None
        await asyncio.sleep(0.2)
        assert received == count // 2


@pytest.mark.asyncio
async def test_shutdown():
    received = None
    async with transit() as t:

        @t.register
        @mark_handler(batch=BatchConfig(max_batch_size=100, delay=100))
        async def handler(m: list[int]):
            nonlocal received
            received = len(m)

        for i in range(99):
            await t.dispatch(42)
        assert received is None
        # give it some time to start the tasks
        await asyncio.sleep(0.2)
        await t.shutdown()
        assert received == 99


@pytest.mark.asyncio
async def test_object_handler():
    received = 0

    class Handler:
        @mark_handler()
        async def handler1(self, _: int):
            nonlocal received
            received += 1

        @mark_handler()
        async def handler2(self, _: str):
            nonlocal received
            received += 1

        @mark_handler()
        async def handler3(self, _: float):
            nonlocal received
            received += 1

    async with transit() as t:
        t.register(Handler())
        await t.dispatch(42)
        await t.dispatch(42.0)
        await t.dispatch("42")
        await asyncio.sleep(1)
        await t.shutdown()
        assert received == 3
