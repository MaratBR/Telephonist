import logging
from typing import Optional

import aioredis
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from server.database import init_database, shutdown_database
from server.internal.channels import get_channel_layer, start_backplane, stop_backplane
from server.internal.channels.backplane import BackplaneBase, RedisBackplane
from server.routes import *
from server.settings import settings


def create_app(
    motor_client: Optional[AsyncIOMotorClient] = None, backplane: Optional[BackplaneBase] = None
):
    app = FastAPI()
    logger = logging.getLogger("telephonist.application")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_api_router)
    app.include_router(application_api_router)
    app.include_router(user_api_router)

    @app.get("/")
    def index(request: Request):
        return {
            "host": request.base_url,
            "headers": request.headers,
            "ip": request.client.host,
        }

    @app.on_event("startup")
    async def _on_startup():
        try:
            await init_database(client=motor_client)
            await start_backplane(
                backplane or RedisBackplane(aioredis.from_url(settings.redis_url))
            )
            await get_channel_layer().start()
        except Exception as exc:
            logger.exception(str(exc))

    @app.on_event("shutdown")
    async def _on_shutdown():
        try:
            await stop_backplane()
            await shutdown_database()
            await get_channel_layer().dispose()
        except Exception as exc:
            logger.exception(str(exc))
            raise

    return app
