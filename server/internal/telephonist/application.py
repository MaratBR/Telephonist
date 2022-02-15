import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import HTTPException
from pydantic import Field, ValidationError, parse_obj_as, validator
from starlette import status

from server.internal.channels import get_channel_layer
from server.internal.telephonist import realtime
from server.internal.telephonist.utils import CG, Errors
from server.models.common import (
    AppBaseModel,
    Identifier,
    IdProjection,
    convert_to_utc,
)
from server.models.telephonist import (
    Application,
    ConnectionInfo,
    EventSequence,
)
from server.models.telephonist.application_task import (
    ApplicationTask,
    TaskTrigger,
    TaskTypesRegistry,
)


class CreateApplication(AppBaseModel):
    name: Identifier
    display_name: str
    description: Optional[str] = Field(max_length=3000)
    tags: Optional[List[str]]
    disabled: bool = False
    application_type: str = Application.ARBITRARY_TYPE


async def create_new_application(create_application: CreateApplication):
    if await Application.find(
        Application.name == create_application.name
    ).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Application with given name already exists",
        )
    app = Application(
        display_name=create_application.display_name,
        name=create_application.name,
        description=create_application.description,
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


async def get_application(application_id: PydanticObjectId):
    return Errors.raise404_if_none(
        await Application.get(application_id),
        message=f"Application with id={id} not found",
    )


async def get_application_task(
    app_id: PydanticObjectId, task_id: UUID, *, fetch_links: bool = False
):
    task = await ApplicationTask.find_one(
        {"_id": task_id},
        ApplicationTask.NOT_DELETED_COND,
        fetch_links=fetch_links,
    )
    if task is None:
        raise HTTPException(
            404, f"application task with id {task_id} not found"
        )
    if task.app_id != app_id:
        raise HTTPException(
            401,
            f"application task with if {task_id} does not belong to the"
            f" application with id {app_id}",
        )
    return task


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
    task_type: TaskTypesRegistry.KeyType = TaskTypesRegistry.ARBITRARY
    body: Optional[Any]
    env: Dict[str, str] = Field(default_factory=dict)
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


async def define_application_task(app: Application, body: DefineTask):
    task_type, task_body = parse_task_type_or_raise(body.task_type, body.body)
    await raise_if_application_task_name_taken(app.id, body.name)
    task = ApplicationTask(
        app_id=app.id,
        name=body.name,
        qualified_name=app.name + "/" + body.name,
        description=body.name,
        body=task_body,
        task_type=task_type,
        env=body.env,
        app=app,
    )
    await task.insert()
    await on_application_task_updated(task)
    return task


async def deactivate_application_task(task: ApplicationTask):
    await task.soft_delete()
    await on_application_task_deleted(task)


async def on_application_task_deleted(task: ApplicationTask):
    await get_channel_layer().group_send(
        CG.app(task.app_id), "task_removed", task.id
    )


class TaskUpdate(AppBaseModel):
    class Missing:
        ...

    description: Optional[str]
    tags: Optional[List[str]]
    task_type: Optional[TaskTypesRegistry.KeyType]
    body: Optional[Any] = Missing
    name: Optional[str]
    env: Optional[Dict[str, str]]
    triggers: Optional[List[TaskTrigger]]


async def apply_application_task_update(
    task: ApplicationTask, update: TaskUpdate
):
    if update.body is not TaskUpdate.Missing or update.task_type is not None:
        if update.body is not TaskUpdate.Missing:
            task.body = update.body
        if update.task_type:
            task.task_type = update.task_type
        task.task_type, task.body = parse_task_type_or_raise(
            task.task_type, update.task_type
        )
    if update.name is not None:
        await raise_if_application_task_name_taken(task.app_id, update.name)
        task.name = update.name
        task.qualified_name = (
            task.qualified_name.split("/")[0] + "/" + update.name
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
    await on_application_task_updated(task)
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
            task_type=t.task_type,
            body=t.body,
            triggers=t.triggers,
        )


class SyncResult(AppBaseModel):
    tasks: List[DefinedTask] = Field(default_factory=list)
    errors: Dict[UUID, str] = Field(default_factory=dict)


async def sync_defined_tasks(
    app: Application, tasks: List[DefinedTask]
) -> SyncResult:
    db_tasks: Dict[UUID, ApplicationTask] = {
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

                # validation
                try:
                    db_task.task_type, db_task.body = parse_task_type_or_raise(
                        task.task_type, task.body
                    )
                except InvalidTask as exc:
                    result.errors[task.id] = str(exc)
                    continue

                await db_task.replace()
        else:
            try:
                task.task_type, task.body = parse_task_type_or_raise(
                    task.task_type, task.body
                )
            except InvalidTask as exc:
                result.errors[task.id] = str(exc)
                continue
            db_task = ApplicationTask(
                name=task.name,
                qualified_name=app.name + "/" + task.name,
                app_id=app.id,
                description=task.description,
                tags=task.tags,
                env=task.env,
                body=task.body,
                triggers=task.triggers,
                task_type=task.task_type,
            )
            await db_task.insert()
            result.tasks.append(DefinedTask.from_db(db_task))

    result.tasks += [DefinedTask.from_db(t) for t in db_tasks.values()]
    result.tasks = sorted(result.tasks, key=lambda t: t.name)

    return result


async def on_application_task_updated(task: ApplicationTask):
    await get_channel_layer().group_send(
        CG.monitoring.app(task.app_id), "task", task
    )
    await get_channel_layer().group_send(
        CG.app(task.app_id), "task_updated", DefinedTask.from_db(task)
    )


class ApplicationClientInfo(AppBaseModel):
    name: str
    version: str
    compatibility_key: str
    os_info: str
    connection_uuid: UUID
    machine_id: str = Field(max_length=200)
    instance_id: Optional[UUID]

    def get_fingerprint(self):
        return hashlib.sha256(
            json.dumps(
                [1, self.name, self.compatibility_key]
            ).encode()  # 1 - fingerprint version
        ).hexdigest()


class TakenConnectionID(HTTPException):
    def __init__(self):
        super(TakenConnectionID, self).__init__(
            409, "this connection id is already taken, chose another one"
        )


async def get_or_create_connection(
    app_id: PydanticObjectId, info: ApplicationClientInfo, ip_address: str
):
    connection = await ConnectionInfo.find_one(
        ConnectionInfo.id == info.connection_uuid
    )

    if connection is None:
        connection = ConnectionInfo(
            id=info.connection_uuid,
            ip=ip_address,
            client_name=info.name,
            client_version=info.version,
            app_id=app_id,
            fingerprint=info.get_fingerprint(),
            os=info.os_info,
            is_connected=True,
            machine_id=info.machine_id,
            instance_id=info.instance_id,
        )
        await connection.insert()
    else:
        connection.is_connected = True
        connection.machine_id = info.machine_id
        connection.instance_id = info.instance_id
        connection.os = info.os_info
        connection.app_id = app_id
        connection.client_name = info.name
        connection.client_version = info.version
        connection.fingerprint = info.get_fingerprint()
        connection.ip = ip_address
        await connection.save_changes()
    await realtime.on_connection_info_changed(connection)
    return connection


async def on_connection_disconnected(connection: ConnectionInfo):
    connection.is_connected = False
    connection.expires_at = datetime.utcnow() + timedelta(hours=12)
    connection.disconnected_at = datetime.utcnow()
    await connection.save_changes()
    await realtime.on_connection_info_changed(connection)


async def set_sequences_frozen(
    app_id: PydanticObjectId,
    sequences_ids: List[PydanticObjectId],
    frozen: bool,
):
    await EventSequence.find(In("_id", sequences_ids)).update(
        {"frozen": frozen}
    )
    await realtime.on_sequences_updated(
        app_id, sequences_ids, {"frozen": frozen}
    )


async def add_connection_subscription(connection_id: UUID, events: List[str]):
    if len(events) == 0:
        return
    await ConnectionInfo.find({"_id": connection_id}).update(
        {
            "$addToSet": {
                "event_subscriptions": events[0]
                if len(events) == 1
                else {"$each": events}
            }
        }
    )


async def remote_connection_subscription(
    connection_id: UUID, events: List[str]
):
    if len(events) == 0:
        return
    await ConnectionInfo.find({"_id": connection_id}).update(
        {
            "$pull": {
                "event_subscriptions": events[0]
                if len(events) == 1
                else {"$each": events}
            }
        }
    )
