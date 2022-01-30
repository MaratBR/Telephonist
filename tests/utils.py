from starlette.testclient import TestClient


def get_user_token(client: TestClient):
    if hasattr(client, "__user_token__"):
        return client.__user_token__
    d = client.post(
        "/auth/token",
        json={"login": "TEST1", "password": "TEST1", "hybrid": False},
    ).json()
    setattr(client, "__user_token__", d["access_token"])
    return d["access_token"]
