from starlette.testclient import TestClient



def test_create_application(auth_client: TestClient):
    resp = auth_client.post(
        "/api/user-v1/applications",
        json={
            "display_name": "My application",
            "name": "application",
            "description": "This is a new application",
            "tags": ["new", "important"],
        },
    )
    assert resp.status_code == 201, resp.text
    app_id = resp.json()["_id"]
    resp = auth_client.get("/api/user-v1/applications/" + app_id)
    assert resp.status_code == 200
    data = resp.json()["app"]
    assert data["_id"] == app_id
    assert data["name"] == "application"
    assert data["display_name"] == "My application"
    assert data["description"] == "This is a new application"

    resp = auth_client.get("/api/user-v1/applications")
    data = resp.json()
    assert "result" in data and isinstance(data["result"], list)
    assert len(data["result"]) >= 1 and any(
        a["_id"] == app_id for a in data["result"]
    )


def test_update_application(auth_client: TestClient):
    resp = auth_client.post(
        "/api/user-v1/applications",
        json={
            "display_name": "My new app",
            "name": "application",
            "description": "This is a new application",
            "tags": ["new", "important"],
        },
    )
    assert "_id" in resp.json(), resp.text
    app_id = resp.json()["_id"]
    resp = auth_client.patch(
        "/api/user-v1/applications/" + app_id,
        json={
            "display_name": "New name"
        }
    )
    assert resp.status_code == 200, resp.text
    resp = auth_client.get(f"/api/user-v1/applications/{app_id}")
    data = resp.json()
    assert 'app' in data and 'display_name' in data['app'], resp.text
    assert data['app']['display_name'] == 'New name'
