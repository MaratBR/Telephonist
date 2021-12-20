import uuid

import docker
import pytest
from docker.models.containers import Container
from fastapi.testclient import TestClient

from server import app
from server.settings import settings

docker_client = docker.from_env()
settings.redis_url = 'redis://localhost:7379'
settings.mongodb_db_name = 'test_database'
settings.db_url = 'mongodb://localhost:27200'
settings.is_testing = True
settings.create_default_user = True


@pytest.yield_fixture(scope="session")
def redis_container():
    container: Container = docker_client.containers.run('redis', name="telephonist-testing-redis-" + uuid.uuid4().hex,
                                                        detach=True, ports={6379: 7379})
    yield container
    container.remove(force=True)


@pytest.yield_fixture(scope="session")
def mongodb_container():
    container: Container = docker_client.containers.run('mongo', name="telephonist-testing-mongodb-" + uuid.uuid4().hex,
                                                        detach=True, ports={27017: 27200})
    yield container
    container.remove(force=True)


@pytest.fixture(scope="session")
def client_no_init(mongodb_container, redis_container):
    return TestClient(app)


@pytest.yield_fixture(scope="session")
def client(client_no_init: TestClient):
    with client_no_init:
        yield client_no_init
