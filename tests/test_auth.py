import json

from starlette.testclient import TestClient

from server.internal.auth.schema import JWT_CHECK_HASH_COOKIE, JWT_REFRESH_COOKIE


def test_logging_in(client: TestClient):
    assert (
        client.post(
            "/auth/token",
            json={"login": "DoesNotExist", "password": "whatever"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/token",
            json={
                "login": "DoesNotExist",
                "password": "whatever",
                "hybrid": 123,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/auth/token",
            json={"login2": "DoesNotExist", "password": "whatever"},
        ).status_code
        == 422
    )


def test_numbers_allowed_as_usernames_or_passwords(client: TestClient):
    assert (
        client.post("/auth/register", json={"username": 123, "password": 42424242}).status_code
        == 200
    )


def test_registering_and_logging_in(client: TestClient):
    assert (
        client.post(
            "/auth/register",
            json={"username2": "12312", "password": "password"},
        ).status_code
        == 422
    )
    resp = client.post("/auth/register", json={"username": "myUser", "password": "password"})
    assert resp.status_code == 200
    resp = client.post("/auth/token", json={"login": "myUser", "password": "password"})
    assert resp.status_code == 200
    data = json.loads(resp.content)
    assert "refresh_token" in data and "access_token" in data and data["token_type"] == "bearer"
    assert data["refresh_token"] is not None

    resp = client.post(
        "/auth/token",
        json={"login": "myUser", "password": "password", "hybrid": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert (
        "refresh_token" in data and "access_token" in data and data["token_type"] == "hybrid-bearer"
    )
    assert data["refresh_token"] is None
    assert JWT_REFRESH_COOKIE in resp.headers["set-cookie"]
    assert JWT_CHECK_HASH_COOKIE in resp.headers["set-cookie"]


def test_refreshing_token(client: TestClient):
    client.post("/auth/register", json={"username": "myUser22", "password": "password"})
    resp = client.post("/auth/token", json={"login": "myUser22", "password": "password"})
    resp = client.post("/auth/refresh", json={"refresh_token": resp.json()["refresh_token"]})
    data = resp.json()
    assert "refresh_token" in data and "access_token" in data and data["token_type"] == "bearer"
