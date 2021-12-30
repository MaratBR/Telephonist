from typing import Awaitable, Callable, Optional

from fastapi import Depends, Query
from starlette.websockets import WebSocket, WebSocketState

from server.internal.auth.dependencies import parse_jwt_token

NoTokenHandler = Callable[[WebSocket, Exception], Awaitable[None]]


def get_ws_ticket_dependency_function(required: bool, no_token_handler: NoTokenHandler):
    async def dependency_function(websocket: WebSocket, ticket: Optional[str] = Query(None)):
        try:
            assert ticket is not None, "ticket is not set"
            token = parse_jwt_token(ticket)
            assert token.token_type == "ws-ticket", "invalid token type: " + token.token_type
            return token
        except Exception as e:
            if required:
                await no_token_handler(websocket, e)
            else:
                return None

    return dependency_function


async def _default_no_token_handler(ws: WebSocket, _exc: Exception):
    if ws.application_state != WebSocketState.DISCONNECTED:
        await ws.accept()
        await ws.send_text(str(_exc))
        await ws.close(1000)


def WsTicket(required: bool = True, no_token_handler: Optional[NoTokenHandler] = None):  # noqa
    return Depends(
        get_ws_ticket_dependency_function(required, no_token_handler or _default_no_token_handler)
    )
