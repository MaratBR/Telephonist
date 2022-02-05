from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

import pymongo
from beanie import PydanticObjectId, Replace, SaveChanges, before_event
from pydantic import BaseModel, Field

from server.database import register_model
from server.models.common import SoftDeletes
from server.utils.common.type_registry import TypeRegistry


class TriggersRegistry(TypeRegistry[Any]):
    INSTANCE: "TriggersRegistry"


class TaskTypesRegistry(TypeRegistry[Any]):
    INSTANCE: "TaskTypesRegistry"
    ARBITRARY = "arbitrary"
    SCRIPT = "script"
    EXEC = "exec"
    DEFAULT = ARBITRARY


TriggersRegistry.INSTANCE = TriggersRegistry()
TaskTypesRegistry.INSTANCE = TaskTypesRegistry()


class TaskTrigger(BaseModel):
    name: str
    body: Any


TaskTypesRegistry.INSTANCE.update(
    {
        TaskTypesRegistry.EXEC: str,
        TaskTypesRegistry.SCRIPT: str,
        TaskTypesRegistry.ARBITRARY: Dict[str, Any],
    }
)

# TODO add more types
TriggersRegistry.INSTANCE.update(cron=str, events=str, fsnotify=str)


@register_model
class ApplicationTask(SoftDeletes):
    id: UUID = Field(default_factory=uuid4)
    app_id: PydanticObjectId
    name: str
    qualified_name: str
    __name_before_deleted: Optional[str] = None
    description: Optional[str]
    tags: List[str] = Field(default_factory=list)
    triggers: List[TaskTrigger] = Field(default_factory=list)
    body: Optional[Any]
    task_type: str
    env: Dict[str, str] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    @before_event([Replace, SaveChanges])
    def test(self):
        self.last_updated = datetime.utcnow()

    @classmethod
    def find_task(cls, task_id_or_qname: Union[str, PydanticObjectId]):
        return cls.find_one(
            {"_id": task_id_or_qname}
            if isinstance(task_id_or_qname, PydanticObjectId)
            else {"qualified_name": task_id_or_qname}
        )

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
        self.qualified_name = self.__name_before_deleted + " (DELETED)"
        self.name = self.__name_before_deleted + " (DELETED)"
        await super(ApplicationTask, self).soft_delete()

    class Collection:
        name = "application_tasks"
        indexes = [pymongo.IndexModel("qualified_name", unique=True), "app_id"]

    class Settings:
        use_state_management = True
