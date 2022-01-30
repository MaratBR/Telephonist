import enum
from typing import Any, Dict, List, Optional

import pymongo
from beanie import PydanticObjectId
from pydantic import BaseModel, Field

from server.database import register_model
from server.models.common import SoftDeletes
from server.utils.common.type_registry import TypeRegistry


class TriggersRegistry(TypeRegistry[Any]):
    INSTANCE: "TriggersRegistry"


class TaskTypesRegistry(TypeRegistry[Any]):
    INSTANCE: "TaskTypesRegistry"


TriggersRegistry.INSTANCE = TriggersRegistry()
TaskTypesRegistry.INSTANCE = TaskTypesRegistry()


class TaskTrigger(BaseModel):
    name: str
    body: Any


TaskTypesRegistry.INSTANCE.update(script=str, exec=str, arbitrary=Dict[str, Any])

# TODO add more types
TriggersRegistry.INSTANCE.update(cron=str, events=List[str])


@register_model
class ApplicationTask(SoftDeletes):
    app_id: PydanticObjectId
    name: str
    __name_before_deleted: Optional[str] = None
    description: Optional[str]
    tags: List[str] = Field(default_factory=list)
    triggers: List[TaskTrigger] = Field(default_factory=list)
    body: Optional[Any]
    task_type: str
    env: Dict[str, str] = Field(default_factory=dict)

    @classmethod
    def get_body_type(cls, task_type: str):
        if task_type is None:
            return None
        return TaskTypesRegistry.INSTANCE.get(task_type, Any)

    @classmethod
    def exists(cls, name: str):
        return cls.find(cls.name == name).exists()

    async def soft_delete(self):
        if self.deleted_at:
            return
        if self.__name_before_deleted is None:
            self.__name_before_deleted = self.name
        self.name = self.__name_before_deleted + " (DELETED)"
        await super(ApplicationTask, self).soft_delete()

    class Collection:
        name = "application_tasks"
        indexes = [pymongo.IndexModel("name", unique=True), "app_id"]

    class Settings:
        use_state_management = True
