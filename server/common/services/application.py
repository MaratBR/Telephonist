import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import Field
from starlette import status

from server.common.channels import get_channel_layer
from server.common.channels.layer import ChannelLayer
from server.common.models import AppBaseModel, Identifier
from server.database import (
    Application,
    AppLog,
    ConnectionInfo,
    Event,
    EventSequence,
)

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
    _logger = logging.getLogger("telephonist.api.services.ApplicationService")

    def __init__(
        self, channel_layer: ChannelLayer = Depends(get_channel_layer)
    ):
        self._channel_layer = channel_layer

    async def wipe_application(self, app_id: str):
        self._logger.warning(f"Wiping application {app_id}...")
        sequences: list[EventSequence] = await EventSequence.find(
            EventSequence.app_id == app_id
        ).to_list()
        for sequence in sequences:
            await Event.find(Event.sequence_id == sequence.id).delete()
            await AppLog.find(AppLog.sequence_id == sequence.id).delete()
            await sequence.delete()

    async def delete(self, application: Application):
        if application.deleted_at:
            return
        application.deleted_at = datetime.utcnow()
        application.name = "[DELETED] " + application.name
        application.display_name = (
            "[DELETED] " + application.display_name
            if application.display_name.strip() != ""
            else ""
        )
        await application.save()

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
