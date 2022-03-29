import inspect
import logging
import warnings
from typing import Optional, TypeVar

import motor.motor_asyncio
from beanie import Document, init_beanie
from motor.core import AgnosticDatabase
from pymongo.errors import CollectionInvalid

from server.settings import get_settings

_models = set()
_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
_logger = logging.getLogger("telephonist.database")


def motor_client():
    assert _client is not None, "Database is not initialized yet!"
    return _client


def get_database() -> AgnosticDatabase:
    return motor_client()[get_settings().mongodb_db_name]


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
    client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None,
):
    _logger.info(
        "initializing database... (settings.mongodb_db_name=%s)",
        get_settings().mongodb_db_name,
    )
    global _client
    if client:
        warnings.warn(
            "Motor client has been explicitly set in init_database function"
        )
    _client = client or motor.motor_asyncio.AsyncIOMotorClient(
        get_settings().db_url
    )
    db = _client[get_settings().mongodb_db_name]
    _logger.debug(
        f'initializing models: {", ".join(m.__name__ for m in _models)} ...'
    )
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
                except Exception as exc:
                    raise exc
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
