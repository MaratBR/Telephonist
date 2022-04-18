import asyncio

import pytest

from server.common.transit import dispatch, register_handler, transit_instance
from server.common.transit.transit import BatchConfig


@pytest.mark.asyncio
async def test_simple_transit():
    received = False

    @register_handler()
    async def handler(message: int):
        assert message == 42
        nonlocal received
        received = True

    await dispatch(42)
    await asyncio.sleep(0.5)
    assert received
    await transit_instance.shutdown()


@pytest.mark.asyncio
async def test_batch_transit():
    count = 10
    received = None

    @register_handler(batch=BatchConfig(max_batch_size=count, delay=1))
    async def handle(batch: list[int]):
        nonlocal received
        received = len(batch)

    for i in range(5):
        await dispatch(42)
    await asyncio.sleep(0.5)
    assert received is None
    await asyncio.sleep(0.55)
    assert received == 5


@pytest.mark.asyncio
async def test_batch_cap():
    count = 10
    received = None

    @register_handler(batch=BatchConfig(max_batch_size=count, delay=1))
    async def handle(batch: list[int]):
        nonlocal received
        received = len(batch)

    for i in range(count + count // 2):
        await dispatch(42)
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

    @register_handler(batch=BatchConfig(max_batch_size=100, delay=100))
    async def handler(m: list[int]):
        nonlocal received
        received = len(m)

    for i in range(99):
        await dispatch(42)
    assert received is None
    # give it some time to start the tasks
    await asyncio.sleep(0.1)
    await transit_instance.shutdown()
    assert received == 99
