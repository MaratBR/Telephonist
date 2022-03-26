from fastapi import FastAPI

from server.application_api.rest_api import rest_router
from server.application_api.ws_api import ws_router

__all__ = ("application_api",)

application_api = FastAPI()

application_api.include_router(rest_router)
application_api.include_router(ws_router)
