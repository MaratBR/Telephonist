from datetime import datetime
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from beanie import PydanticObjectId
from fastapi import Depends, HTTPException
from pydantic import Field, validator

from server.common.channels.layer import ChannelLayer, get_channel_layer
from server.common.models import AppBaseModel, Identifier, convert_to_utc
from server.common.utils import Errors
from server.database import Application
from server.database.task import ApplicationTask, TaskBody, TaskTrigger


class DefineTask(AppBaseModel):
    id: UUID = Field(
        alias="_id", default_factory=uuid4
    )  # for the sake of consistency
    name: Identifier
    description: str = ""
    body: TaskBody
    body: Optional[Any]
    env: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    triggers: list[TaskTrigger] = Field(default_factory=list)
    display_name: Optional[str]


class InvalidTask(HTTPException):
    def __init__(self, message: str):
        super(InvalidTask, self).__init__(422, message)


class DefinedTask(DefineTask):
    last_updated: datetime
    _last_updated_validator = validator("last_updated", allow_reuse=True)(
        convert_to_utc
    )

    @classmethod
    def from_db(cls, t: ApplicationTask) -> "DefinedTask":
        return DefinedTask(
            _id=t.id,
            tags=t.tags,
            env=t.env,
            description=t.description,
            name=t.name,
            last_updated=t.last_updated,
            body=t.body,
            triggers=t.triggers,
        )


class TaskUpdate(AppBaseModel):
    class Missing:
        ...

    description: Optional[str]
    tags: Optional[list[str]]
    body: Optional[TaskBody]
    env: Optional[dict[str, str]]
    triggers: Optional[list[TaskTrigger]]
    display_name: Optional[str]


class TaskService:
    def __init__(
        self, channel_layer: ChannelLayer = Depends(get_channel_layer)
    ):
        self._channel_layer = channel_layer

    async def notify_task_changed(self, task: ApplicationTask):
        await self._channel_layer.group_send(
            f"m/app/{task.app_id}", "task", task
        )
        await self._channel_layer.group_send(
            f"a/{task.app_id}", "task_updated", DefinedTask.from_db(task)
        )

    async def apply_application_task_update(
        self, task: ApplicationTask, update: TaskUpdate
    ):
        task.body = task.body if update.body is None else update.body
        task.display_name = (
            task.display_name if update.display_name else update.display_name
        )
        task.env = task.env if update.env is None else update.env
        task.triggers = (
            task.triggers if update.triggers is None else update.triggers
        )
        task.description = (
            task.description
            if update.description is None
            else update.description
        )
        task.tags = task.tags if update.tags is None else update.tags
        await task.save_changes()
        return task

    async def raise_if_application_task_name_taken(
        self, app_id: PydanticObjectId, name: str
    ):
        if await ApplicationTask.find(
            ApplicationTask.app_id == app_id, ApplicationTask.name == name
        ).exists():
            raise HTTPException(
                409,
                f'task with name "{name}" for application {app_id} already'
                " exists",
            )

    async def define_task(self, app: Application, body: DefineTask):
        await self.raise_if_application_task_name_taken(app.id, body.name)
        task = ApplicationTask(
            app_name=app.name,
            app_id=app.id,
            name=body.name,
            qualified_name=app.name + "/" + body.name,
            description=body.description,
            body=body.body,
            display_name=body.display_name,
            env=body.env,
            app=app,
        )
        await task.insert()
        return task

    async def deactivate_application_task(self, task: ApplicationTask):
        await task.soft_delete()
        await self._channel_layer.group_send(
            f"a/{task.app_id}", "task_removed", task.id
        )

    async def get_task_or_404(self, task_id_or_name: Union[str, UUID]):
        if isinstance(task_id_or_name, UUID):
            message = f"application task with _id={task_id_or_name} not found"
            find = {"_id": task_id_or_name}
        else:
            message = f"application task with _id={task_id_or_name} not found"
            find = {"qualified_name": task_id_or_name}
        return Errors.raise404_if_none(
            await ApplicationTask.find_one(
                find,
                ApplicationTask.NOT_DELETED_COND,
            ),
            message,
        )

    async def get_application_tasks(
        self, app_id: PydanticObjectId, include_deleted: bool = False
    ):
        return (
            await (
                ApplicationTask
                if include_deleted
                else ApplicationTask.not_deleted()
            )
            .find(ApplicationTask.app_id == app_id)
            .to_list()
        )
