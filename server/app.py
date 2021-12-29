from fastapi import FastAPI
from loguru import logger
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from server.database import init_database, shutdown_database
from server.internal.channels import get_channel_layer, start_backplane, stop_backplane
from server.logging import create_logger
from server.routes import *
from server.settings import settings


def create_app():
    app = FastAPI()
    app.logger = create_logger()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(users_router)
    app.include_router(auth_router)
    app.include_router(events_router)
    app.include_router(applications_router)

    @app.get("/")
    def index(request: Request):
        return {
            "host": request.base_url,
            "headers": request.headers,
            "ip": request.client.host,
        }

    @app.on_event("startup")
    async def _on_startup():
        await init_database()
        await start_backplane(settings.redis_url)
        await get_channel_layer().start()

    @app.on_event("shutdown")
    async def _on_shutdown():
        try:
            await stop_backplane()
            await shutdown_database()
            await get_channel_layer().dispose()
        except Exception as exc:
            logger.exception(exc)
            raise

    return app


app = create_app()
