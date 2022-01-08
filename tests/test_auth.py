import json

import pytest
from starlette.testclient import TestClient

LOG_IN_REQUESTS = [
    ({"login": "DoesNotExist", "password": "whatever"}, 401),
    ({"login": "admin", "password": "admin"}, 200),
]


@pytest.mark.parametrize("desc", LOG_IN_REQUESTS)
def test_logging_in(desc, client: TestClient):
    assert client.post("/auth/token", json=desc[0]).status_code == desc[1]


LOG_IN_PASSWORD_RESET = [("TEST1", "TEST1", False), ("admin", "admin", True)]


@pytest.mark.parametrize("desc", LOG_IN_PASSWORD_RESET)
def test_password_reset_token(desc, client: TestClient):
    resp = client.post("/auth/token", json={"login": desc[0], "password": desc[1], "hybrid": False})
    assert resp.status_code == 200
    d = resp.json()
    if desc[2]:
        assert d["access_token"] is None
        assert d["password_reset_required"]
        assert d["password_reset_token"]
    else:
        assert d["access_token"]
        assert not d["password_reset_required"]
        assert d["password_reset_token"] is None


def test_refreshing_token(client: TestClient):
    resp = client.post("/auth/token", json={"login": "TEST1", "password": "TEST1", "hybrid": False})
    resp = client.post("/auth/refresh", json={"refresh_token": resp.json()["refresh_token"]})
    data = resp.json()
    assert "refresh_token" in data and "access_token" in data and data["token_type"] == "bearer"
