import asyncio
import inspect
import logging
from typing import Optional, TypeVar

import motor.motor_asyncio
from beanie import Document, init_beanie
from motor.core import AgnosticDatabase
from pymongo.errors import CollectionInvalid

from server.settings import Settings

_models = set()
_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
_database: Optional[motor.motor_asyncio.AsyncIOMotorDatabase] = None
_logger = logging.getLogger("telephonist.database")


def motor_client():
    assert _client is not None, "Database is not initialized yet!"
    return _client


def get_database() -> AgnosticDatabase:
    assert _database is not None, "Database is not initialized yet!"
    return _database


async def _ping_loop():
    try:
        while _client:
            await _client
    except asyncio.CancelledError:
        pass


TModelType = TypeVar("TModelType")  # bound=Type[Document]


def register_model(model: TModelType) -> TModelType:
    if model in _models:
        return
    assert issubclass(
        model, Document
    ), "model must subclass Document task_type"
    _models.add(model)
    return model


is_available = False


async def init_database(
    settings: Settings,
    client: motor.motor_asyncio.AsyncIOMotorClient,
    database_name: str,
):
    _logger.info(
        "initializing database... (settings.mongodb_db_name=%s)",
        database_name,
    )
    global _client, _database
    _client = client
    _database = _client[database_name]

    _logger.debug(
        f'initializing models: {", ".join(m.__name__ for m in _models)} ...'
    )
    for model in _models:
        if hasattr(model, "__motor_create_collection_params__"):
            params = getattr(model, "__motor_create_collection_params__")(
                settings
            )
            if params:
                try:
                    try:
                        name = model.Collection.name
                    except AttributeError:
                        name = model.__name__
                    await _database.create_collection(name, **params)
                except CollectionInvalid:
                    pass
                except Exception as exc:
                    raise exc
    await init_beanie(database=_database, document_models=list(_models))

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
