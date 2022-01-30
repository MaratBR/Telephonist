import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from beanie import PydanticObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, parse_obj_as
from starlette import status

from server.internal.channels import get_channel_layer
from server.internal.telephonist import realtime
from server.internal.telephonist.utils import CG, Errors
from server.models.telephonist import Application, ConnectionInfo
from server.models.telephonist.application_settings import get_default_settings_for_type
from server.models.telephonist.application_task import (
    ApplicationTask,
    TaskTrigger,
    TaskTypesRegistry,
)
from server.settings import settings


class CreateApplication(BaseModel):
    name: str
    description: Optional[str] = Field(max_length=400)
    tags: Optional[List[str]]
    disabled: bool = False
    application_type: str = Application.ARBITRARY_TYPE


async def create_new_application(create_application: CreateApplication):
    if (
        create_application.application_type
        not in (Application.ARBITRARY_TYPE, Application.AGENT_TYPE)
        and not settings.allow_custom_application_types
    ):
        raise HTTPException(422, "invalid application type, custom application types are disabled")
    if await Application.find(Application.name == create_application.name).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Application with given name already exists",
        )
    app = Application(
        name=create_application.name,
        description=create_application.description,
        disabled=create_application.disabled,
        tags=[] if create_application.tags is None else list(set(create_application.tags)),
        application_type=create_application.application_type,
        settings=get_default_settings_for_type(create_application.application_type),
    )
    await app.save()
    return app


class ApplicationUpdate(BaseModel):
    name: Optional[str]
    description: Optional[str] = Field(max_length=400)
    disabled: Optional[bool]
    tags: Optional[List[str]]


async def get_application(application_id: PydanticObjectId):
    return Errors.raise404_if_none(
        await Application.get(application_id), message=f"Application with id={id} not found"
    )


async def get_application_task(app_id: PydanticObjectId, task_id: PydanticObjectId):
    task = await ApplicationTask.get_not_deleted(task_id)
    if task is None:
        raise HTTPException(404, f"application task with id {task_id} not found")
    if task.app_id != app_id:
        raise HTTPException(
            401,
            f"application task with if {task_id} does not belong to the application with id"
            f" {app_id}",
        )


async def get_application_tasks(app_id: PydanticObjectId, include_deleted: bool = False):
    return (
        await (ApplicationTask if include_deleted else ApplicationTask.not_deleted())
        .find(ApplicationTask.app_id == app_id)
        .to_list()
    )


class DefineTask(BaseModel):
    name: str
    description: Optional[str]
    type: Optional[TaskTypesRegistry.KeyType]
    body: Optional[Any]
    env: Dict[str, str] = Field(default_factory=dict)


def parse_body_type_or_raise(body_type: Optional[TaskTypesRegistry.KeyType], body: Optional[Any]):
    body_type = body_type or TaskTypesRegistry
    type_ = ApplicationTask.get_body_type(body_type)
    if type_ is None:
        if body is not None:
            raise HTTPException(
                422,
                f'invalid task body, body must be empty (null), since type "{body_type}" doesn\'t'
                " allow a body",
            )
        return body_type, None
    else:
        try:
            return body_type, parse_obj_as(type_, body)
        except ValidationError:
            raise HTTPException(422, f"invalid task body, body must be assignable to type {type_}")


async def raise_if_application_task_name_taken(app_id: PydanticObjectId, name: str):
    if await ApplicationTask.find(
        ApplicationTask.app_id == app_id, ApplicationTask.name == name
    ).exists():
        raise HTTPException(409, f'task with name "{name}" for application {app_id} already exists')


async def define_application_task(app: Application, body: DefineTask):
    task_type, task_body = parse_body_type_or_raise(body.type, body.body)
    await raise_if_application_task_name_taken(app.id, body.name)
    task = ApplicationTask(
        app_id=app.id,
        name=body.name,
        description=body.name,
        body=task_body,
        type=body.type,
        task_type=task_type,
        env=body.env,
    )
    await task.insert()
    await realtime.on_application_task_updated(task)
    return task


async def deactivate_application_task(task: ApplicationTask):
    await task.soft_delete()
    await realtime.on_application_task_deleted(task.id, task.app_id)


class TaskUpdate(BaseModel):
    class Missing:
        ...

    description: Optional[str]
    tags: Optional[List[str]]
    type: Optional[TaskTypesRegistry.KeyType]
    body: Optional[Any] = Missing
    name: Optional[str]
    env: Optional[Dict[str, str]]
    triggers: Optional[List[TaskTrigger]]


async def apply_application_task_update(task: ApplicationTask, update: TaskUpdate):
    if update.body is not TaskUpdate.Missing or update.type is not None:
        if update.body is not TaskUpdate.Missing:
            task.body = update.body
        if update.type:
            task.task_type = update.type
        task.task_type, task.body = parse_body_type_or_raise(task.task_type, update.type)
    if update.name is not None:
        await raise_if_application_task_name_taken(task.app_id, update.name)
        task.name = update.name
    task.env = task.env if update.env is None else update.env
    task.triggers = task.triggers if update.triggers is None else update.triggers
    task.description = task.description if update.description is None else update.description
    task.tags = task.tags if update.tags is None else update.tags
    await task.save_changes()
    await realtime.on_application_task_updated(task)
    return task


class ApplicationClientInfo(BaseModel):
    name: str
    version: str
    compatibility_uuid: UUID
    os_info: str
    connection_uuid: UUID
    machine_id: str = Field(max_length=50)
    instance_id: Optional[UUID]
    __fingerprint: Optional[str] = None

    @property
    def fingerprint(self):
        if self.__fingerprint is None:
            self.__fingerprint = hashlib.sha256(
                json.dumps([1, self.name, str(self.compatibility_uuid)])  # fingerprint version
            ).hexdigest()
        return self.__fingerprint


async def get_or_create_connection(
    app_id: PydanticObjectId, info: ApplicationClientInfo, ip_address: str
):
    connection = await ConnectionInfo.find_one(ConnectionInfo.id == info.connection_uuid)

    if connection is None:
        connection = ConnectionInfo(
            id=info.connection_uuid,
            ip=ip_address,
            client_name=info.name,
            client_version=info.version,
            app_id=app_id,
            fingerprint=info.fingerprint,
            os=info.os_info,
            is_connected=True,
            machine_id=info.machine_id,
            instance_id=info.instance_id,
        )
    else:
        if connection.is_connected:
            # TODO do something about this idk
            raise RuntimeError("the connection is already marked as connected")

        connection.is_connected = True
        connection.machine_id = info.machine_id
        connection.instance_id = info.instance_id
        connection.os = info.os_info
        connection.app_id = app_id
        connection.client_name = info.name
        connection.client_version = info.version
        connection.fingerprint = info.fingerprint
        connection.ip = ip_address
        await connection.save_changes()
    await realtime.on_connection_info_changed(connection)
    return connection


async def on_connection_disconnected(connection: ConnectionInfo):
    connection.is_connected = False
    connection.expires_at = datetime.utcnow() + timedelta(hours=12)
    connection.disconnected_at = datetime.utcnow()
    await connection.save_changes()


async def add_connection_subscription(connection_id: UUID, events: List[str]):
    if len(events) == 0:
        return
    await ConnectionInfo.find({"_id": connection_id}).update(
        {"$addToSet": {"event_subscriptions": events[0] if len(events) == 1 else {"$each": events}}}
    )


async def remote_connection_subscription(connection_id: UUID, events: List[str]):
    if len(events) == 0:
        return
    await ConnectionInfo.find({"_id": connection_id}).update(
        {"$pull": {"event_subscriptions": events[0] if len(events) == 1 else {"$each": events}}}
    )
