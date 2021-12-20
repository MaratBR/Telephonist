from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from server.database import init_database, shutdown_database
from server.internal.channels import stop_backplane, start_backplane, get_channel_layer
from server.routes import auth_router, events_router, applications_router, application_hosts_router
from server.settings import settings

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(auth_router)
app.include_router(events_router)
app.include_router(applications_router)
app.include_router(application_hosts_router)


@app.get('/')
def index(request: Request):
    return {
        'host': request.base_url,
        'headers': request.headers,
        'ip': request.client.host
    }


@app.on_event('startup')
async def _on_startup():
    await init_database()
    await start_backplane(settings.redis_url)
    await get_channel_layer().start()


@app.on_event('shutdown')
async def _on_shutdown():
    try:
        await stop_backplane()
        await shutdown_database()
        await get_channel_layer().dispose()
    except Exception as exc:
        print(exc)
        raise
