import logging
import time
from typing import Any, Callable, Coroutine, Optional, cast

import aioredis
import async_timeout
import motor.motor_asyncio
import nanoid
import orjson
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from server import VERSION
from server.application_api import application_api
from server.common.channels import get_channel_layer
from server.common.channels.backplane import (
    BackplaneBase,
    InMemoryBackplane,
    RedisBackplane,
    get_backplane,
    start_backplane,
    stop_backplane,
)
from server.database import init_database, shutdown_database
from server.l10n import Localization
from server.settings import DebugSettings, Settings, settings
from server.spa import SPA
from server.user_api import user_api


class TelephonistApp(FastAPI):
    def __init__(
        self,
        settings: Settings,
        backplane: Optional[BackplaneBase] = None,
        motor_client: Optional[AsyncIOMotorClient] = None,
        **kwargs,
    ):
        kwargs.setdefault("default_response_class", ORJSONResponse)
        super(TelephonistApp, self).__init__(**kwargs)
        self.settings = settings
        self._backplane = backplane
        self._motor_client = (
            motor_client
            or motor.motor_asyncio.AsyncIOMotorClient(settings.db_url)
        )
        self.logger = logging.getLogger("telephonist.application")
        self.localization = Localization(
            localedir="./locales", supported_locales=["en_US", "ru_RU"]
        )
        self._init_middlewares()
        self._init_routers()

        if settings.spa_path:
            self.mount(
                "/",
                SPA(
                    directory=settings.spa_path,
                    api_path_check=lambda path: path.startswith("api/")
                    or path == "api",
                ),
            )

        self.add_event_handler("startup", self._on_startup)
        self.add_event_handler("shutdown", self._on_shutdown)
        self.add_api_route("/api/hc", self._hc)

        self.add_api_route(
            "/api/__debug__",
            cast(
                Callable[[], Coroutine[Any, Any, Response]],
                self.__debug_route__,
            ),
        )

    @staticmethod
    async def _generate_request_id(request: Request, call_next):
        request.scope["request-id"] = nanoid.generate()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.scope["request-id"]
        return response

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        settings.set(self.settings)
        await super(TelephonistApp, self).__call__(scope, receive, send)

    async def __debug_route__(self, request: Request):
        return {
            "headers": dict(request.headers),
            "client": [request.client.host, request.client.port],
            "settings": self.settings,
        }

    @staticmethod
    async def _index():
        return {"detail": "OK"}

    @staticmethod
    async def _backplane_hc():
        now = time.time_ns()
        try:
            async with async_timeout.timeout(0.5):
                await get_backplane().ping()
            latency = (time.time_ns() - now) / 1000000
            d = {
                "healthy": True,
                "latency_ms": latency,
            }
        except Exception as exc:
            d = {"healthy": False, "exception": {"type": type(exc).__name__}}

        d = {"type": type(get_backplane()).__name__, "status": d}
        return d

    async def _hc(self):
        return {"modules": {"backplane": await self._backplane_hc()}}

    async def _on_startup(self):
        self.logger.info(f"RUNNING TELEPHONIST VERSION {VERSION}")
        self.logger.info(f"\tcookies_policy = {self.settings.cookies_policy}")
        self.logger.info(f"\tcors_origins = {self.settings.cors_origins}")
        self.logger.info(f"\tdb_url = {self.settings.db_url}")
        self.logger.info(f"\tredis_url = {self.settings.redis_url}")

        try:
            FastAPICache.init(InMemoryBackend())
            await init_database(
                self._motor_client, self.settings.mongodb_db_name
            )

            self.logger.info(
                f"backplane backend: {self.settings.backplane_backend}"
            )

            if (
                self.settings.backplane_backend
                == Settings.BackplaneBackend.REDIS
            ):
                await start_backplane(
                    RedisBackplane(aioredis.from_url(settings.get().redis_url))
                )
            elif (
                self.settings.backplane_backend
                == Settings.BackplaneBackend.MEMORY
            ):
                await start_backplane(InMemoryBackplane())
            else:
                raise RuntimeError(
                    "unknown backplane_backend:"
                    f" {self.settings.backplane_backend}"
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
        self.include_router(user_api, prefix="/api/user-v1")
        self.include_router(application_api, prefix="/api/application-v1")

    def _init_middlewares(self):
        self.add_middleware(self.localization.middleware)
        self.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=[
                "X-CSRF-Token",
                "Authorization",
                "Content-Type",
            ],
        )
        self.middleware("http")(self._generate_request_id)


def create_production_app():
    return TelephonistApp(Settings())


def create_debug_app():
    class ORJSONIdentResponse(ORJSONResponse):
        def render(self, content: Any) -> bytes:
            return orjson.dumps(content, option=orjson.OPT_INDENT_2)

    app = TelephonistApp(
        DebugSettings(), default_response_class=ORJSONIdentResponse
    )
    return app
