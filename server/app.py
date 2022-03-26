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

from server.application_api import application_api
from server.auth.internal.sessions import (
    RedisSessionBackend,
    init_sessions_backend,
)
from server.common.channels import (
    get_channel_layer,
    start_backplane,
    stop_backplane,
)
from server.common.channels.backplane import (
    BackplaneBase,
    RedisBackplane,
    get_backplane,
)
from server.database import init_database, shutdown_database
from server.settings import settings
from server.user_api import user_api_application
from server.ws_root_router import ws_root_router


class TelephonistApp(FastAPI):
    def __init__(
        self,
        backplane: Optional[BackplaneBase] = None,
        motor_client: Optional[AsyncIOMotorClient] = None,
    ):
        super(TelephonistApp, self).__init__(
            default_response_class=ORJSONResponse, root_path=settings.root_path
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
        self.add_api_route("/", self._index)

    async def _index(self):
        return ORJSONResponse({"detail": "OK"})

    async def _on_startup(self):
        try:
            FastAPICache.init(InMemoryBackend())
            await init_database(client=self._motor_client)
            await start_backplane(
                self._backplane
                or RedisBackplane(aioredis.from_url(settings.redis_url))
            )
            init_sessions_backend(
                RedisSessionBackend(aioredis.from_url(settings.redis_url))
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
        self.mount("/user-api", user_api_application)
        self.mount("/application-api", application_api)
        self.include_router(ws_root_router)
        self.add_api_route("hc", self._health_check)

    async def _health_check(self):
        return ORJSONResponse(
            {
                "modules": {
                    "database": "?",
                    "backplane": {
                        "type": type(get_backplane()).__name__,
                    },
                }
            }
        )


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
