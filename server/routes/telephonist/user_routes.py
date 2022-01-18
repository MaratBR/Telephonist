from datetime import datetime, timedelta
from typing import Optional, Set, Union

import pydantic
from beanie import PydanticObjectId
from fastapi import APIRouter
from pydantic import BaseModel

from server import VERSION
from server.internal.auth.dependencies import AccessToken
from server.internal.auth.token import JWT, UserTokenModel
from server.internal.channels import WSTicket, WSTicketModel
from server.internal.channels.hub import Hub, bind_message, ws_controller
from server.internal.telephonist.utils import CG
from server.models.auth import User

user_router = APIRouter(tags=["user"], prefix="/user")


@user_router.post("/issue-ws-ticket")
async def issue_ws_ticket(token: UserTokenModel = AccessToken()):
    exp = datetime.now() + timedelta(minutes=2)
    return {"exp": exp, "ticket": WSTicketModel[User](exp=exp, sub=token.sub).encode()}


@ws_controller(user_router, "/ws")
class UserHub(Hub):
    class SubscribeToEvents(BaseModel):
        event_type: Optional[str]
        related_task: Optional[str]
        app_id: Optional[PydanticObjectId]

    ticket: WSTicketModel[User] = WSTicket(User)
    EntryStr = pydantic.constr(regex=r"^[\w\d]+/[\w\d]+$")
    _entries: Set[str] = set()
    _events_group: Optional[str] = None
    _subscription_desc: Optional[SubscribeToEvents] = None

    async def on_connected(self):
        await self.connection.add_to_group(CG.entry("user", self.ticket.sub))
        await self.send_message("introduction", {"server_version": VERSION, "authentication": "ok"})

    @bind_message("unsubscribe_events")
    async def unsubscribe_events(self):
        if self._events_group:
            await self.connection.remove_from_group(self._events_group)
            self._events_group = None
        await self._sync()

    @bind_message("subscribe_events")
    async def subscribe_to_events(self, message: SubscribeToEvents):
        if message.app_id:
            group = CG.application_events(message.app_id)
        else:
            if message.related_task is None and message.event_type is None:
                return
            group = CG.events(message.related_task, message.event_type)
        if self._events_group:
            await self.connection.remove_from_group(self._events_group)
        self._events_group = group
        self._subscription_desc = message
        await self.connection.add_to_group(self._events_group)
        await self._sync()

    @bind_message("subscribe_entry")
    async def subscribe_to_changes(self, entry: EntryStr):
        entry = entry.lower()
        if entry not in self._entries:
            self._entries.add(entry)
            await self.connection.add_to_group(CG.entry(*entry.split("/")))
        await self._sync()

    @bind_message("unsubscribe_entry")
    async def unsubscribe_from_changes(self, entry: EntryStr):
        if entry in self._entries:
            self._entries.remove(entry)
            await self.connection.remove_from_group(CG.entry(*self._entry.split("/")))
        await self._sync()

    async def _sync(self):
        await self.send_message(
            "sync", {"entries": list(self._entries), "events_subscription": self._subscription_desc}
        )
