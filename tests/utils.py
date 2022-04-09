from starlette.testclient import TestClient

from server.auth.sessions import session_cookie


def do_auth_client(client: TestClient):
    resp = client.post("/api/user-v1/auth/login", json={"username": "TEST1", "password": "TEST1"})
    assert resp.status_code == 200
    assert session_cookie.cookie in client.cookies, f'Session cookie is missing: {", ".join(client.cookies.keys())}'
    assert client.get("/api/user-v1/auth/whoami").status_code == 200
    client.headers['X-CSRF-Token'] = resp.json()['csrf']
    return client
