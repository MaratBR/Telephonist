from typing import Awaitable

from beanie import Document
from pydantic import Field


class TaskInfo(Document):
    id: str = Field(alias='_id')
    description: str = ''

    @classmethod
    def exists(cls, task_name: str) -> Awaitable[bool]:
        return cls.find({'_id': task_name}).exists()

    @classmethod
    async def ensure_task(cls, task_name: str):
        await cls.find_one({'_id': task_name}).upsert(on_insert=cls(id=task_name))
