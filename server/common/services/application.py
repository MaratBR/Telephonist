from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import Field
from starlette import status

from server.common.channels import get_channel_layer
from server.common.channels.layer import ChannelLayer
from server.common.models import AppBaseModel, Identifier
from server.database import Application, ConnectionInfo

from .task import DefinedTask


class CreateApplication(AppBaseModel):
    name: Identifier
    display_name: Optional[str]
    description: Optional[str] = Field(max_length=3000, default=None)
    tags: Optional[List[str]]
    disabled: bool = False


class ApplicationUpdate(AppBaseModel):
    display_name: Optional[str]
    description: Optional[str] = Field(max_length=3000)
    disabled: Optional[bool]
    tags: Optional[List[str]]


class SyncResult(AppBaseModel):
    tasks: List[DefinedTask] = Field(default_factory=list)
    errors: dict[UUID, str] = Field(default_factory=dict)


class ApplicationService:
    def __init__(
        self, channel_layer: ChannelLayer = Depends(get_channel_layer)
    ):
        self._channel_layer = channel_layer

    async def create(
        self, create_application: CreateApplication
    ) -> Application:
        if await Application.find(
            Application.name == create_application.name
        ).exists():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Application with given name already exists",
            )
        app = Application(
            display_name=create_application.display_name
            or create_application.name,
            name=create_application.name,
            description=create_application.description or "",
            disabled=create_application.disabled,
            tags=[]
            if create_application.tags is None
            else list(set(create_application.tags)),
        )
        await app.save()
        return app

    async def notify_connection_changed(self, connection: ConnectionInfo):
        await self._channel_layer.groups_send(
            [
                f"m/app/{connection.app_id}",
                f"a/{connection.app_id}",
            ],
            "connection",
            connection,
        )
