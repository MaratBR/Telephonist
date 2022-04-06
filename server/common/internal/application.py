from datetime import datetime, timezone
from typing import Any, List, Optional, Union
from uuid import UUID, uuid4

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import HTTPException
from pydantic import Field, ValidationError, parse_obj_as, validator
from starlette import status

from server.common.channels import get_channel_layer
from server.common.internal.utils import Errors
from server.common.models import AppBaseModel, Identifier, IdProjection, convert_to_utc
from server.database import Application, ConnectionInfo
from server.database.task import (
    ApplicationTask,
    TaskBody,
    TaskTrigger,
    TaskTypesRegistry,
)


class CreateApplication(AppBaseModel):
    name: Identifier
    display_name: Optional[str]
    description: Optional[str] = Field(max_length=3000)
    tags: Optional[List[str]]
    disabled: bool = False

# test_application/my_task/completed
#


async def create_new_application(create_application: CreateApplication):
    if await Application.find(
        Application.name == create_application.name
    ).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Application with given name already exists",
        )
    app = Application(
        display_name=create_application.display_name or create_application.name,
        name=create_application.name,
        description=create_application.description or "",
        disabled=create_application.disabled,
        tags=[]
        if create_application.tags is None
        else list(set(create_application.tags)),
    )
    await app.save()
    return app


class ApplicationUpdate(AppBaseModel):
    display_name: Optional[str]
    description: Optional[str] = Field(max_length=3000)
    disabled: Optional[bool]
    tags: Optional[List[str]]


async def get_application_or_404(application_id: PydanticObjectId):
    return Errors.raise404_if_none(
        await Application.get(application_id),
        message=f"Application with id={id} not found",
    )


async def get_task_or_404(task_id_or_name: Union[UUID, str]):
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
    app_id: PydanticObjectId, include_deleted: bool = False
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


class DefineTask(AppBaseModel):
    id: UUID = Field(
        alias="_id", default_factory=uuid4
    )  # for the sake of consistency
    name: Identifier
    description: str = ""
    body: TaskBody
    body: Optional[Any]
    env: dict[str, str] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    triggers: List[TaskTrigger] = Field(default_factory=list)


class InvalidTask(HTTPException):
    def __init__(self, message: str):
        super(InvalidTask, self).__init__(422, message)


def parse_task_type_or_raise(
    body_type: Optional[TaskTypesRegistry.KeyType], body: Optional[Any]
):
    body_type = body_type or TaskTypesRegistry.ARBITRARY
    type_ = ApplicationTask.get_body_type(body_type)
    if type_ is None:
        if body is not None:
            raise InvalidTask(
                "invalid task body, body must be empty (null), since"
                f' task_type "{body_type}" doesn\'t allow a body',
            )
        return body_type, None
    else:
        try:
            return body_type, parse_obj_as(type_, body)
        except ValidationError:
            raise InvalidTask(
                "invalid task body, body must be assignable to task_type"
                f" {type_}"
            )


async def raise_if_application_task_name_taken(
    app_id: PydanticObjectId, name: str
):
    if await ApplicationTask.find(
        ApplicationTask.app_id == app_id, ApplicationTask.name == name
    ).exists():
        raise HTTPException(
            409,
            f'task with name "{name}" for application {app_id} already exists',
        )


async def define_task(app: Application, body: DefineTask):
    await raise_if_application_task_name_taken(app.id, body.name)
    task = ApplicationTask(
        app_name=app.name,
        app_id=app.id,
        name=body.name,
        qualified_name=app.name + "/" + body.name,
        description=body.name,
        body=body.body,
        env=body.env,
        app=app,
    )
    await task.insert()
    return task


async def deactivate_application_task(task: ApplicationTask):
    await task.soft_delete()
    await on_application_task_deleted(task)


async def on_application_task_deleted(task: ApplicationTask):
    await get_channel_layer().group_send(
        f"a/{task.app_id}", "task_removed", task.id
    )


class TaskUpdate(AppBaseModel):
    class Missing:
        ...

    description: Optional[str]
    tags: Optional[List[str]]
    body: Optional[TaskBody]
    env: Optional[dict[str, str]]
    triggers: Optional[List[TaskTrigger]]
    display_name: Optional[str]


async def apply_application_task_update(
    task: ApplicationTask, update: TaskUpdate
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
        task.description if update.description is None else update.description
    )
    task.tags = task.tags if update.tags is None else update.tags
    await task.save_changes()
    return task


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


class SyncResult(AppBaseModel):
    tasks: List[DefinedTask] = Field(default_factory=list)
    errors: dict[UUID, str] = Field(default_factory=dict)


async def sync_tasks(
    app: Application, tasks: List[DefinedTask]
) -> SyncResult:
    db_tasks: dict[UUID, ApplicationTask] = {
        t.id: t
        for t in await ApplicationTask.not_deleted()
        .find(ApplicationTask.app_id == app.id)
        .to_list()
    }
    tasks_by_name = {t.name: t for t in db_tasks.values()}
    result = SyncResult()
    deleted_tasks = set(
        t.id
        for t in await (
            ApplicationTask.deleted()
            .find(
                ApplicationTask.app_id == app.id,
                In("_id", [t.id for t in tasks]),
            )
            .project(IdProjection)
            .to_list()
        )
    )
    tasks = [t for t in tasks if t.id not in deleted_tasks]

    for task in tasks:
        db_task = db_tasks.get(task.id)

        if db_task is None:
            # if we can't find task by id but CAN find it by name
            # it means task from the local configuration and the one from the server has mismatching IDs
            db_task = tasks_by_name.get(task.name)

        if db_task:
            if (
                db_task.last_updated.replace(tzinfo=timezone.utc)
                < task.last_updated
            ):
                db_task.last_updated = task.last_updated
                db_task.env = task.env
                db_task.description = task.description
                db_task.tags = task.tags
                db_task.body = task.body
                db_task.name = task.name
                db_task.triggers = task.triggers

                # TODO validate body, maybe?

                await db_task.replace()
        else:
            # TODO validate body, maybe?
            db_task = ApplicationTask(
                name=task.name,
                qualified_name=app.name + "/" + task.name,
                app_id=app.id,
                description=task.description,
                tags=task.tags,
                env=task.env,
                body=task.body,
                triggers=task.triggers,
            )
            await db_task.insert()
            result.tasks.append(DefinedTask.from_db(db_task))

    result.tasks += [DefinedTask.from_db(t) for t in db_tasks.values()]
    result.tasks = sorted(result.tasks, key=lambda t: t.name)

    return result


async def notify_task_changed(task: ApplicationTask):
    await get_channel_layer().group_send(
        f"m/app/{task.app_id}", "task", task
    )
    await get_channel_layer().group_send(
        f"a/{task.app_id}", "task_updated", DefinedTask.from_db(task)
    )


async def notify_connection_changed(connection: ConnectionInfo):
    await get_channel_layer().groups_send(
        [
            f"m/app/{connection.app_id}",
            f"a/{connection.app_id}",
        ],
        "connection",
        connection,
    )
