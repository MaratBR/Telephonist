from fastapi import FastAPI

from server.auth.routes import router as auth_router
from server.telephonist.routes import router as telephonist_router
from .channels.broadcast import broadcast
from .database import init_database, shutdown_database

app = FastAPI()

app.include_router(auth_router, prefix='/auth')
app.include_router(telephonist_router)


@app.on_event('startup')
async def _on_startup():
    await init_database()
    await broadcast.connect()


@app.on_event('shutdown')
async def _on_shutdown():
    try:
        await broadcast.disconnect()
        await shutdown_database()
    except Exception as exc:
        print(exc)
