from fastapi import FastAPI
from starlette.requests import Request
from starlette.websockets import WebSocket


def get_application(
    *, request: Request = None, websocket: WebSocket = None
) -> FastAPI:
    if request:
        assert isinstance(request.app, FastAPI)
        return request.app
    if websocket:
        assert isinstance(websocket.app, FastAPI)
        return websocket.app
    raise RuntimeError("invalid params: must specify request of websocket")


def get_client_ip(
    *, request: Request = None, websocket: WebSocket = None
) -> str:
    if request:
        return request.client.host
    if websocket:
        return websocket.client.host
    raise RuntimeError("invalid params: must specify request of websocket")
