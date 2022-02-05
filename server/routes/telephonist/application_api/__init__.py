from fastapi import APIRouter

from server.routes.telephonist.application_api.rest_api import rest_router
from server.routes.telephonist.application_api.ws_api import ws_router

__all__ = ("application_api_router",)

application_api_router = APIRouter(prefix="/application-api", tags=["application-api"])

application_api_router.include_router(rest_router)
application_api_router.include_router(ws_router)
