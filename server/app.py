import logging
import time
from typing import Any, Callable, Coroutine, Optional, cast

import aioredis
import async_timeout
import motor.motor_asyncio
import nanoid
import orjson
from fastapi import Depends, FastAPI
from fastapi.responses import ORJSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response

from server import VERSION
from server.application_api import application_api
from server.common.channels.backplane import (
    BackplaneBase,
    InMemoryBackplane,
    RedisBackplane,
    get_backplane,
    start_backplane,
    stop_backplane,
)
from server.common.channels.layer import (
    start_channel_layer,
    stop_channel_layer,
)
from server.common.services.events import EventsEventHandlers
from server.common.services.sequence import SequenceEventHandlers
from server.common.transit import transit_instance
from server.database import init_database, shutdown_database
from server.l10n import Localization
from server.settings import DebugSettings, Settings
from server.spa import SPA
from server.user_api import user_api


class Test:
    def __init__(self, request: Request, a: str):
        self.a = a
        self.request = request


class Test2:
    def __init__(self, t: Test = Depends()):
        self.t = t


class TelephonistApp(FastAPI):
    def __init__(
        self,
        settings: Settings,
        backplane: Optional[BackplaneBase] = None,
        **kwargs,
    ):
        kwargs.setdefault("default_response_class", ORJSONResponse)
        super(TelephonistApp, self).__init__(**kwargs)
        self.settings = settings
        self.state.settings = settings
        self.logger = logging.getLogger("telephonist.application")
        self.localization = Localization(
            localedir="./locales", supported_locales=["en_US", "ru_RU"]
        )

        self._backplane = backplane
        self._motor_client = None
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
        self.add_api_route("/", self._index)
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

    async def __debug_route__(self, request: Request):
        return {
            "headers": dict(request.headers),
            "client": [request.client.host, request.client.port],
            "settings": self.settings,
            "scheme": request.scope["scheme"],
        }

    @staticmethod
    async def _index(t: Test2 = Depends()):
        return {"detail": "OK" + t.t.a + t.t.request.client.host}

    async def _backplane_hc(self):
        now = time.time_ns()
        try:
            async with async_timeout.timeout(0.5):
                await get_backplane(self).ping()
            latency = (time.time_ns() - now) / 1000000
            d = {
                "healthy": True,
                "latency_ms": latency,
            }
        except Exception as exc:
            d = {"healthy": False, "exception": {"type": type(exc).__name__}}

        d = {"type": type(get_backplane(self)).__name__, "status": d}
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
            self._motor_client = motor.motor_asyncio.AsyncIOMotorClient(
                self.settings.db_url
            )
            transit_instance.register(SequenceEventHandlers(self))
            transit_instance.register(EventsEventHandlers())
            FastAPICache.init(InMemoryBackend())
            await init_database(
                self.settings,
                self._motor_client,
                self.settings.mongodb_db_name,
            )

            self.logger.info(
                f"backplane backend: {self.settings.backplane_backend}"
            )

            if (
                self.settings.backplane_backend
                == Settings.BackplaneBackend.REDIS
            ):
                await start_backplane(
                    self,
                    RedisBackplane(aioredis.from_url(self.settings.redis_url)),
                )
            elif (
                self.settings.backplane_backend
                == Settings.BackplaneBackend.MEMORY
            ):
                await start_backplane(self, InMemoryBackplane())
            else:
                raise RuntimeError(
                    "unknown backplane_backend:"
                    f" {self.settings.backplane_backend}"
                )
            await start_channel_layer(self)
        except Exception as exc:
            self.logger.exception(str(exc))
            raise

    async def _on_shutdown(self):
        try:
            transit_instance.unregister_all_of_type(SequenceEventHandlers)
            transit_instance.unregister_all_of_type(EventsEventHandlers)
            await shutdown_database()
            await stop_backplane(self)
            await stop_channel_layer(self)
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
