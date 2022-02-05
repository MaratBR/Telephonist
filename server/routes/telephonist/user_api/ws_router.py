from datetime import datetime, timedelta
from typing import List

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter
from pydantic import BaseModel

from server import VERSION
from server.internal.auth.dependencies import AccessToken
from server.internal.channels import WSTicket, WSTicketModel
from server.internal.channels.hub import Hub, bind_message, ws_controller
from server.internal.telephonist import CG
from server.models.auth import User
from server.models.common import Identifier, IdProjection
from server.models.telephonist import Application

ws_router = APIRouter(prefix="/ws")


@ws_router.get("/issue-ws-ticket")
async def issue_user_ws_ticket(token=AccessToken()):
    exp = datetime.utcnow() + timedelta(minutes=5)
    return {"ticket": WSTicketModel[User](exp=exp, sub=token.sub).encode(), "exp": exp}


@ws_controller(ws_router, "/")
class UserHub(Hub):
    ticket: WSTicketModel[User] = WSTicket(User)

    async def on_connected(self):
        await self.connection.add_to_group(CG.user(self.ticket.sub))
        await self.send_message("introduction", {"server_version": VERSION, "authentication": "ok"})

    @bind_message("unsub_from_app_events")
    async def unsubscribe_from_application_events(self, app_ids: List[PydanticObjectId]):
        applications = await Application.find(In("_id", app_ids)).project(IdProjection).to_list()
        self._application_events -= applications
        await self._sync()

    @bind_message("sub_to_app_events")
    async def subscribe_from_application_events(self, app_ids: List[PydanticObjectId]):
        applications = await Application.find(In("_id", app_ids)).project(IdProjection).to_list()
        self._application_events += applications
        await self._sync()

    class EntryDescriptor(BaseModel):
        entry_type: Identifier
        id: PydanticObjectId

        def __str__(self):
            return self.entry_type + "/" + str(self.id)

    @bind_message("subscribe_entry")
    async def subscribe_to_changes(self, entry: EntryDescriptor):
        if str(entry) not in self._entries:
            self._entries.add(str(entry))
            await self.connection.add_to_group(CG.entry(entry.entry_type, entry.id))
        await self._sync()

    @bind_message("unsubscribe_entry")
    async def unsubscribe_from_changes(self, entry: EntryDescriptor):
        if entry in self._entries:
            self._entries.remove(str(entry))
            await self.connection.remove_from_group(CG.entry(entry.entry_type, entry.id))
        await self._sync()

    async def _sync(self):
        await self.send_message(
            "sync",
            {
                "entries": [
                    self.EntryDescriptor(entry_type=et, id=i)
                    for et, i in map(lambda v: v.split("/"), self._entries)
                ],
                "application_events": list(self._application_events),
            },
        )
