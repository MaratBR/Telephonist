from starlette.testclient import TestClient

from server.auth.sessions import session_cookie


def auth_client(client: TestClient):
    resp = client.post("/api/user-v1/auth/login", json={"username": "TEST1", "password": "TEST1"})
    assert resp.status_code == 200
    print(resp.cookies)
    print(resp.headers)
    assert session_cookie.cookie in client.cookies, f'Session cookie is missing: {", ".join(client.cookies.keys())}'
    return client
