import asyncio
import uuid

import docker
import pytest
from docker.models.containers import Container
from fastapi.testclient import TestClient

from server.app import create_app
from server.settings import settings

docker_client = docker.from_env()
settings.redis_url = "redis://localhost:7379"
settings.mongodb_db_name = "test_database"
settings.db_url = "mongodb://localhost:27200"
settings.is_testing = True


def create_test_app():
    app = create_app()

    @app.on_event("startup")
    async def create_test_users():
        from server.models.auth import User

        tasks = []
        for i in range(5):
            tasks.append(User.create_user(f"TEST{i + 1}", f"TEST{i + 1}"))
        await asyncio.gather(*tasks)

    return app


def _kill_old_containers():
    for c in docker_client.containers.list(filters={"label": "telephonist-testing"}):
        c: Container
        c.kill()
        c.remove()


@pytest.yield_fixture(scope="session")
def redis_container():
    _kill_old_containers()
    container: Container = docker_client.containers.run(
        "redis",
        name="telephonist-testing-redis-" + uuid.uuid4().hex,
        detach=True,
        ports={6379: 7379},
        auto_remove=True,
        labels=["telephonist-testing"],
    )
    yield container
    container.remove(force=True)


@pytest.yield_fixture(scope="session")
def mongodb_container():
    _kill_old_containers()
    container: Container = docker_client.containers.run(
        "mongo",
        name="telephonist-testing-mongodb-" + uuid.uuid4().hex,
        detach=True,
        ports={27017: 27200},
        auto_remove=True,
    )
    yield container
    container.remove(force=True)


@pytest.fixture(scope="session")
def client_no_init(mongodb_container, redis_container):
    return TestClient(create_test_app())


@pytest.yield_fixture(scope="session")
def client(client_no_init: TestClient):
    with client_no_init:
        yield client_no_init
