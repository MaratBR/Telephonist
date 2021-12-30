from starlette.testclient import TestClient

from server.settings import settings


def get_user_token(client: TestClient):
    d = client.post(
        "/auth/token",
        json={
            "login": settings.default_username,
            "password": settings.default_password,
        },
    ).json()
    return d["access_token"]


def test_create_application(client: TestClient):
    client.headers["authorization"] = "Bearer " + get_user_token(client)
    resp = client.post(
        "/applications",
        json={
            "name": "My application",
            "description": "This is a new application",
            "tags": ["new", "important"],
        },
    )
    assert resp.status_code == 201
    app_id = resp.json()["id"]
    resp = client.get("/applications/" + app_id)
    assert resp.status_code == 200
    data = resp.json()
    assert data["_id"] == app_id
    assert data["name"] == "My application"
    assert data["description"] == "This is a new application"

    resp = client.get("/applications")
    data = resp.json()
    assert "result" in data and isinstance(data["result"], list)
    assert len(data["result"]) >= 1 and any(a["_id"] == app_id for a in data["result"])