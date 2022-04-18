import asyncio

import async_timeout
import pytest

from server.common.channels.backplane import InMemoryBackplane


@pytest.mark.asyncio
async def test_backplane_pubsub():
    backplane = InMemoryBackplane()

    async def send_after():
        await asyncio.sleep(0.1)
        await backplane.publish("test", {"data": 42})

    message = None

    await backplane.start()
    task = asyncio.create_task(send_after())
    async with backplane.subscribe("test") as sub:
        try:
            async with async_timeout.timeout(0.3):
                async for tuple_ in sub:
                    message = tuple_
        except asyncio.TimeoutError:
            pass
    await backplane.stop()

    await asyncio.sleep(0.1)
    assert task is not None
    assert task.done()
    assert message is not None
    channel, message_data = message
    assert channel == "test"
    assert message_data == {"data": 42}


@pytest.mark.asyncio
async def test_backplane_pubsub_2():
    backplane = InMemoryBackplane()

    async def send_after():
        await asyncio.sleep(0.1)
        await backplane.publish("test", {"data": 42})
        await backplane.publish("test2", {"data": 24})

    messages = {}

    await backplane.start()
    task = asyncio.create_task(send_after())
    async with backplane.subscribe("test", "test2") as sub:
        try:
            async with async_timeout.timeout(1):
                async for channel, data in sub:
                    assert channel not in messages
                    assert isinstance(data, dict) and "data" in data
                    messages[channel] = data["data"]
        except asyncio.TimeoutError:
            pass

    await backplane.stop()
    await asyncio.sleep(0.1)
    assert task is not None
    assert task.done()
    assert len(messages) == 2
    assert messages["test"] == 42
    assert messages["test2"] == 24
