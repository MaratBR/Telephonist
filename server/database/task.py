from datetime import datetime
from typing import Any, List, Optional, Union
from uuid import UUID, uuid4

import pymongo
from beanie import PydanticObjectId
from pydantic import Field

from server.common.models import AppBaseModel, SoftDeletes
from server.database.registry import register_model
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


class TaskTrigger(AppBaseModel):
    name: str
    body: Any


TaskTypesRegistry.INSTANCE.update(
    {
        TaskTypesRegistry.EXEC: str,
        TaskTypesRegistry.SCRIPT: str,
        TaskTypesRegistry.ARBITRARY: dict[str, Any],
    }
)

# TODO add more types
TriggersRegistry.INSTANCE.update(cron=str, events=str, fsnotify=str)


class TaskBody(AppBaseModel):
    type_: str = Field(alias="type", default=TaskTypesRegistry.ARBITRARY)
    value: Optional[Any] = Field(default_factory=dict)


@register_model
class ApplicationTask(SoftDeletes):
    id: UUID = Field(default_factory=uuid4, alias="_id")
    app_id: PydanticObjectId
    name: str
    qualified_name: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    display_name: Optional[str] = None
    triggers: List[TaskTrigger] = Field(default_factory=list)
    body: TaskBody = Field(default_factory=TaskBody)
    env: dict[str, str] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def find_task(cls, task_id_or_qname: Union[str, UUID]):
        return cls.find_one(
            {"_id": task_id_or_qname}
            if isinstance(task_id_or_qname, UUID)
            else {"qualified_name": task_id_or_qname},
            cls.NOT_DELETED_COND,
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
        self.qualified_name = self.name + " (DELETED)"
        self.name = self.name + " (DELETED)"
        await super(ApplicationTask, self).soft_delete()

    class Collection:
        name = "application_tasks"
        indexes = [
            pymongo.IndexModel("qualified_name", unique=True),
            "app_id",
            [
                ("name", pymongo.TEXT),
                ("qualified_name", pymongo.TEXT),
                ("description", pymongo.TEXT),
                ("tags", pymongo.TEXT),
                ("env", pymongo.TEXT),
            ],
        ]

    class Settings:
        use_state_management = True
