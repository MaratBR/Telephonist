import logging
from typing import Optional

import aioredis
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocket

from server.database import init_database, shutdown_database
from server.internal.channels import (
    get_channel_layer,
    start_backplane,
    stop_backplane,
)
from server.internal.channels.backplane import BackplaneBase, RedisBackplane, get_backplane
from server.routes import (
    application_api_router,
    auth_api_router,
    user_api_router,
    ws_root_router,
)
from server.settings import settings


class TelephonistApp(FastAPI):
    def __init__(
        self,
        backplane: Optional[BackplaneBase] = None,
        motor_client: Optional[AsyncIOMotorClient] = None,
    ):
        super(TelephonistApp, self).__init__(
            default_response_class=ORJSONResponse
        )
        self._backplane = backplane
        self._motor_client = motor_client
        self.logger = logging.getLogger("telephonist.application")
        self.settings = settings
        self.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.cors_origin,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._init_routers()

        self.add_event_handler("startup", self._on_startup)
        self.add_event_handler("shutdown", self._on_shutdown)

    async def _on_startup(self):
        try:
            FastAPICache.init(InMemoryBackend())
            await init_database(client=self._motor_client)
            await start_backplane(
                self._backplane
                or RedisBackplane(aioredis.from_url(settings.redis_url))
            )
            await get_channel_layer().start()
        except Exception as exc:
            self.logger.exception(str(exc))
            raise

    async def _on_shutdown(self):
        try:
            await stop_backplane()
            await shutdown_database()
            await get_channel_layer().dispose()
        except Exception as exc:
            self.logger.exception(str(exc))
            raise

    def _init_routers(self):
        self.include_router(auth_api_router)
        self.include_router(application_api_router)
        self.include_router(user_api_router)
        # see https://github.com/tiangolo/fastapi/pull/2640
        # (when it's merged we can remove ws_root_router
        # and replace it with something else)
        self.include_router(ws_root_router)

        self.add_api_route("/hc", self._health_check)

    async def _health_check(self):
        return ORJSONResponse({
            "modules": {
                "database": "?",
                "backplane": {
                    "type": type(get_backplane()).__name__,
                }
            }
        })


def create_app(
    motor_client: Optional[AsyncIOMotorClient] = None,
    backplane: Optional[BackplaneBase] = None,
):
    app = TelephonistApp(backplane=backplane, motor_client=motor_client)

    # TODO REMOVE!!!
    @app.websocket_route("/")
    async def echo(ws: WebSocket):  # not really echo but whatever
        await ws.accept()
        while True:
            msg = await ws.receive()
            if msg and msg.get("type") == "websocket.disconnect":
                break

    return app
