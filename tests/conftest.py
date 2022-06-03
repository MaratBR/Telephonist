import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import async_timeout
import motor.motor_asyncio
import pytest
from fastapi.testclient import TestClient

from server.app import TelephonistApp
from server.settings import TestingSettings
from tests.api_tests.conftest import MONGODB_PORT
from tests.utils import do_auth_client


@pytest.fixture(scope="session")
def settings():
    return TestingSettings()


def create_test_app(settings):
    settings.cookies_policy = "Strict"
    settings.redis_url = "redis://localhost:7379"
    settings.mongodb_db_name = "test_database" + uuid.uuid4().hex
    settings.db_url = f"mongodb://localhost:{MONGODB_PORT}"

    app = TelephonistApp(settings)

    @app.on_event("startup")
    async def create_test_users():
        from server.auth.models import User

        for i in range(10):
            print(f"CREATING USER{i}")
            await User.create_user(
                f"TEST{i*10}", f"TEST{i}", password_reset_required=i % 2 == 0
            )

    return app


@pytest.fixture(scope="session")
def application(settings):
    print("CREATING APPLICATION")
    return create_test_app(settings)


@pytest.fixture(scope="session")
def client_no_init(mongodb_server, application):
    return TestClient(application, base_url="https://localhost.ru/")


@pytest.fixture()
def client(client_no_init: TestClient):
    with client_no_init:
        yield client_no_init


@pytest.fixture()
def auth_client(client: TestClient):
    do_auth_client(client)
    return client
