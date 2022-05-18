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
