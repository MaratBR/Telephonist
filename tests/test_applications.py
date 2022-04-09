from starlette.testclient import TestClient

from tests.utils import auth_client


def test_create_application(client: TestClient):
    auth_client(client)
    resp = client.post(
        "/api/user-v1/applications",
        json={
            "display_name": "My application",
            "name": "applications",
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
    assert data["name"] == "application"
    assert data["display_name"] == "My application"
    assert data["description"] == "This is a new application"

    resp = client.get("/api/user-v1/applications")
    data = resp.json()
    assert "result" in data and isinstance(data["result"], list)
    assert len(data["result"]) >= 1 and any(
        a["_id"] == app_id for a in data["result"]
    )
