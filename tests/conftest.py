import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import TelephonistApp
from server.settings import TestingSettings
from tests.utils import do_auth_client

MONGODB_PORT = 27222


@pytest.yield_fixture(scope="session")
def mongodb_server():
    r = subprocess.run(["mongod", "--help"], capture_output=True)
    assert r.returncode == 0, "mongod executable is not available"
    data_path = "/tmp/TELEPHONIST" + str(uuid.uuid4())
    Path(data_path).mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["mongod", "--dbpath", data_path, "--port", str(MONGODB_PORT)],
        stdout=subprocess.PIPE,
    )
    yield proc
    proc.kill()
    os.system(f"rm -rf {data_path}")


def create_test_app():
    settings = TestingSettings()
    settings.use_non_secure_cookies = True
    settings.cookies_policy = "Strict"
    settings.redis_url = "redis://localhost:7379"
    settings.mongodb_db_name = "test_database" + uuid.uuid4().hex
    settings.db_url = f"mongodb://localhost:{MONGODB_PORT}"

    app = TelephonistApp(settings)

    @app.on_event("startup")
    async def create_test_users():
        from server.auth.models import User

        tasks = []
        for i in range(10):
            tasks.append(
                User.create_user(
                    f"TEST{i}", f"TEST{i}", password_reset_required=i % 2 == 0
                )
            )
        await asyncio.gather(*tasks)

    return app


@pytest.fixture(scope="session")
def application():
    return create_test_app()


@pytest.fixture()
def client_no_init(mongodb_server, application):
    return TestClient(application, base_url="https://localhost.ru/")


@pytest.yield_fixture()
def client(client_no_init: TestClient):
    with client_no_init:
        yield client_no_init


@pytest.fixture()
def auth_client(client: TestClient):
    do_auth_client(client)
    return client
