import asyncio

import async_timeout
import motor.motor_asyncio
import pytest

MONGODB_PORT = 27222


async def _check_mongodb_connection(connection_string):
    client = motor.motor_asyncio.AsyncIOMotorClient(connection_string)
    try:
        async with async_timeout.timeout(1.5):
            await client.admin.command({"ping": 1})
        return True
    except:
        return False


@pytest.fixture(autouse=True)
async def mongodb_server():
    if not await _check_mongodb_connection(
        f"mongodb://localhost:{MONGODB_PORT}"
    ):
        print(
            "MongoDB is not running! Trying to run mongo in docker without"
            " sudo."
        )
        pytest.skip(
            "MongoDB is not running, no way to test this. \nPlease run"
            f" mongodb on port {MONGODB_PORT}: sudo docker run -p"
            f" {MONGODB_PORT}:27017 mongo"
        )
