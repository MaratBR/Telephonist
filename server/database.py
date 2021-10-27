import asyncio
from functools import partial
from typing import TypeVar, Optional

import motor.motor_asyncio
from beanie import Document, init_beanie
from pymongo.errors import DuplicateKeyError

from server.settings import settings

_models = set()
_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None


def motor_client():
    assert _client is not None, 'Database is not initialized yet!'
    return _client


TModelType = TypeVar('TModelType')  # bound=Type[Document]


def register_model(model: TModelType) -> TModelType:
    assert issubclass(model, Document), 'model must subclass Document type'
    _models.add(model)
    return model


async def init_database():
    global _client
    _client = motor.motor_asyncio.AsyncIOMotorClient(settings.db_url)
    await init_beanie(database=_client.telephonist, document_models=list(_models))

    init_coroutines = []

    async def populate(model):
        try:
            await model.populate()
        except DuplicateKeyError:
            pass

    for model in _models:
        if hasattr(model, 'populate') and callable(model.populate):
            init_coroutines.append(partial(populate, model)())
    await asyncio.gather(*init_coroutines)


async def shutdown_database():
    pass
