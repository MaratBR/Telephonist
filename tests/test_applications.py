from starlette.testclient import TestClient

from tests.utils import get_user_token


def test_create_application(client: TestClient):
    client.headers["authorization"] = "Bearer " + get_user_token(client)
    resp = client.post(
        "/user-api/applications",
        json={
            "name": "My application",
            "description": "This is a new application",
            "tags": ["new", "important"],
        },
    )
    assert resp.status_code == 201
    app_id = resp.json()["_id"]
    resp = client.get("/user-api/applications/" + app_id)
    assert resp.status_code == 200
    data = resp.json()["app"]
    assert data["_id"] == app_id
    assert data["name"] == "My application"
    assert data["description"] == "This is a new application"

    resp = client.get("/user-api/applications")
    data = resp.json()
    assert "result" in data and isinstance(data["result"], list)
    assert len(data["result"]) >= 1 and any(a["_id"] == app_id for a in data["result"])
