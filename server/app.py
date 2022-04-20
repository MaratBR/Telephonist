import logging
import sys
import time
from typing import Optional, Type

import aioredis
import async_timeout
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from server.application_api import application_api
from server.auth.sessions import (
    InMemorySessionBackend,
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
    InMemoryBackplane,
    RedisBackplane,
    get_backplane,
)
from server.database import init_database, shutdown_database
from server.settings import DebugSettings, Settings, get_settings, use_settings
from server.user_api import user_api


class TelephonistApp(FastAPI):
    def __init__(
        self,
        backplane: Optional[BackplaneBase] = None,
        motor_client: Optional[AsyncIOMotorClient] = None,
    ):
        super(TelephonistApp, self).__init__(
            default_response_class=ORJSONResponse,
            root_path=get_settings().root_path,
        )
        self._backplane = backplane
        self._motor_client = motor_client
        self.logger = logging.getLogger("telephonist.application")
        self.settings = get_settings()
        print(self.settings.cors_origins)
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
        self._init_routers()

        self.add_event_handler("startup", self._on_startup)
        self.add_event_handler("shutdown", self._on_shutdown)
        self.add_api_route("/", self._index)
        self.add_api_route("/hc", self._hc)
        self.add_api_route("/api/__debug__", self.__debug_route__)

    @staticmethod
    async def __debug_route__(request: Request):
        return ORJSONResponse(
            {
                "headers": dict(request.headers),
                "client": [request.client.host, request.client.port],
            }
        )

    async def _index(self):
        return ORJSONResponse({"detail": "OK"})

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

        return ORJSONResponse(
            {"modules": {"backplane": await self._backplane_hc()}}
        )

    async def _on_startup(self):
        try:
            settings = get_settings()
            FastAPICache.init(InMemoryBackend())
            await init_database(client=self._motor_client)

            self.logger.info(
                f"backplane backend: {settings.backplane_backend}"
            )
            self.logger.info(f"sessions backend: {settings.session_backend}")

            if settings.backplane_backend == Settings.BackplaneBackend.REDIS:
                await start_backplane(
                    RedisBackplane(aioredis.from_url(get_settings().redis_url))
                )
            elif (
                settings.backplane_backend == Settings.BackplaneBackend.MEMORY
            ):
                await start_backplane(InMemoryBackplane())
            else:
                raise RuntimeError(
                    f"unknown backplane_backend: {settings.backplane_backend}"
                )

            if settings.session_backend == Settings.SessionBackend.REDIS:
                init_sessions_backend(
                    RedisSessionBackend(
                        aioredis.from_url(get_settings().redis_url)
                    )
                )
            elif settings.session_backend == Settings.SessionBackend.MEMORY:
                init_sessions_backend(InMemorySessionBackend())
            else:
                raise RuntimeError(
                    f"unknown session_backend: {settings.session_backend}"
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


def _use_settings(settings: Type[Settings]):
    try:
        use_settings(settings)
    except ValidationError as err:
        for err_dict in err.errors():
            err_type = err_dict["type"]
            env_var = (
                settings.Config.env_prefix.upper() + err_dict["loc"][0].upper()
            )
            if err_type == "value_error.missing":
                print(
                    f"[ERROR] Environment variable {env_var} is missing",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[ERROR] Environment variable {env_var} is invalid:"
                    f' {err_dict["msg"]}',
                    file=sys.stderr,
                )
        print(
            "[ERROR] Errors in settings detected, see above", file=sys.stderr
        )
        exit(1)


def create_production_app():
    _use_settings(Settings)
    return TelephonistApp()


def create_debug_app():
    _use_settings(DebugSettings)
    return TelephonistApp()
