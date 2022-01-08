from datetime import timedelta, datetime
from typing import Optional, Set, Union

import pydantic
from beanie import PydanticObjectId
from fastapi import APIRouter
from pydantic import BaseModel

from server.internal.auth.dependencies import AccessToken
from server.internal.auth.token import UserTokenModel, JWT
from server.internal.channels import WSTicketModel, WSTicket
from server.internal.channels.hub import Hub, bind_message, ws_controller
from server.internal.telephonist.utils import CG
from server.models.auth import User

user_router = APIRouter(tags=["user"], prefix="/user")


@user_router.post("/issue-ws-ticket")
async def issue_ws_ticket(token: UserTokenModel = AccessToken()):
    exp = datetime.now() + timedelta(minutes=2)
    return {
        "exp": exp,
        "ticket": WSTicketModel[User](exp=exp, sub=token.sub).encode()
    }


@ws_controller(user_router, "/ws")
class UserHub(Hub):
    ticket: WSTicketModel[User] = WSTicket(User)
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
