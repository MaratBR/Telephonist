import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient

from server.app import create_app
from server.internal.channels.backplane import InMemoryBackplane
from server.settings import settings


MONGODB_PORT = 27222

settings.redis_url = "redis://localhost:7379"
settings.mongodb_db_name = "test_database" + uuid.uuid4().hex
settings.db_url = f"mongodb://localhost:{MONGODB_PORT}"
settings.is_testing = True


@pytest.yield_fixture(scope="session")
def mongodb_server():
    r = subprocess.run(["mongod", "--help"], capture_output=True)
    assert r.returncode == 0, "mongod executable is not available"
    data_path = "/tmp/TELEPHONIST" + str(uuid.uuid4())
    Path(data_path).mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["mongod", "--dbpath", data_path, "--port", str(MONGODB_PORT)], stdout=subprocess.PIPE)
    yield proc
    proc.kill()
    os.system(f"rm -rf {data_path}")


def create_test_app():
    app = create_app(backplane=InMemoryBackplane())

    @app.on_event("startup")
    async def create_test_users():
        from server.models.auth import User
        tasks = []
        for i in range(10):
            tasks.append(User.create_user(f"TEST{i}", f"TEST{i}", password_reset_required=i % 2 == 0))
        await asyncio.gather(*tasks)

    return app


@pytest.fixture(scope="session")
def client_no_init(mongodb_server):
    return TestClient(create_test_app())


@pytest.yield_fixture(scope="session")
def client(client_no_init: TestClient):
    with client_no_init:
        yield client_no_init
