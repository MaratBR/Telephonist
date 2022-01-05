import inspect
from typing import Optional, TypeVar

import motor.motor_asyncio
from beanie import Document, init_beanie
from pymongo.errors import CollectionInvalid

from server.settings import settings

_models = set()
_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None


def motor_client():
    assert _client is not None, "Database is not initialized yet!"
    return _client


TModelType = TypeVar("TModelType")  # bound=Type[Document]


def register_model(model: TModelType) -> TModelType:
    assert issubclass(model, Document), "model must subclass Document type"
    _models.add(model)
    return model


async def init_database():
    global _client
    _client = motor.motor_asyncio.AsyncIOMotorClient(settings.db_url)
    db = _client.telephonist
    for model in _models:
        if hasattr(model, "__motor_create_collection_params__"):
            params = getattr(model, "__motor_create_collection_params__")()
            if params:
                try:
                    try:
                        name = model.Collection.name
                    except AttributeError:
                        name = model.__name__
                    await db.create_collection(name, **params)
                except CollectionInvalid:
                    pass
    await init_beanie(database=db, document_models=list(_models))

    for model in _models:
        if hasattr(model, "on_database_ready") and inspect.iscoroutinefunction(
            getattr(model, "on_database_ready")
        ):
            try:
                await model.on_database_ready()
            except Exception:
                pass


async def shutdown_database():
    pass
