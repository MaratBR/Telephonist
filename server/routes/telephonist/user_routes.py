from typing import Optional, Set, Union

import pydantic
from beanie import PydanticObjectId
from fastapi import APIRouter
from pydantic import BaseModel

from server.internal.auth.dependencies import AccessToken
from server.internal.channels.hub import Hub, bind_message, ws_controller
from server.internal.telephonist.utils import CG
from server.models.auth import UserTokenModel

user_router = APIRouter(tags=["user"], prefix="/user")


@ws_controller(user_router, "/ws")
class UserHub(Hub):
    token: UserTokenModel = AccessToken()
    EntryStr = pydantic.constr(regex=r"^[\w\d]+/[\w\d]+$")
    _entry: Optional[str] = None
    _events_group: Optional[str] = None

    async def on_connected(self):
        await self.connection.add_to_group(CG.entry("user", self.token.sub))

    class SubscribeToEvents(BaseModel):
        event_type: Optional[str] = ...
        related_task: Optional[str] = ...

    class SubscribeToAppEvents(BaseModel):
        app_id: PydanticObjectId

    @bind_message("subscribe_events")
    async def subscribe_to_events(self, message: Union[SubscribeToAppEvents, SubscribeToEvents]):
        if isinstance(message, self.SubscribeToAppEvents):
            group = CG.application_events(message.app_id)
        else:
            group = CG.events(message.related_task, message.event_type)
        if self._events_group:
            await self.connection.remove_from_group(self._events_group)
        self._events_group = group
        await self.connection.add_to_group(self._events_group)

    @bind_message("subscribe_entry")
    async def subscribe_to_changes(self, entry: EntryStr):
        entry = entry.lower()
        if entry != self._entry:
            self._entry = entry
            await self.connection.add_to_group(CG.entry(*entry.split("/")))

    @bind_message("unsubscribe_entry")
    async def unsubscribe_from_changes(self):
        if self._entry:
            await self.connection.remove_from_group(CG.entry(*self._entry.split("/")))
