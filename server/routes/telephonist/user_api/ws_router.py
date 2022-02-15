from datetime import datetime, timedelta
from typing import List, Optional, Set

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter

from server import VERSION
from server.internal.auth.dependencies import AccessToken
from server.internal.channels import WSTicket, WSTicketModel
from server.internal.channels.hub import Hub, bind_message, ws_controller
from server.internal.telephonist import CG
from server.models.auth import User
from server.models.common import IdProjection
from server.models.telephonist import Application

ws_router = APIRouter(prefix="/ws")


@ws_router.get("/issue-ws-ticket")
async def issue_user_ws_ticket(token=AccessToken()):
    exp = datetime.now() + timedelta(minutes=5)
    return {
        "ticket": WSTicketModel[User](exp=exp, sub=token.sub).encode(),
        "exp": exp,
    }


@ws_controller(ws_router, "")
class UserHub(Hub):
    ticket: WSTicketModel[User] = WSTicket(User)

    def __init__(self):
        super().__init__()
        self._subscribed_application: Optional[PydanticObjectId] = None
        self._application_events: Set[PydanticObjectId] = set()

    async def on_connected(self):
        await self.connection.add_to_group(CG.auth.user(self.ticket.sub))
        await self.send_message(
            "introduction", {"server_version": VERSION, "authentication": "ok"}
        )

    @bind_message("unsub_from_app_events")
    async def unsubscribe_from_application_events(
        self, app_ids: List[PydanticObjectId]
    ):
        for app_id in app_ids:
            await self.connection.remove_from_group(
                CG.application_events(app_id)
            )
        self._application_events = self._application_events.difference(app_ids)
        await self._sync()

    @bind_message("sub_to_app_events")
    async def subscribe_from_application_events(
        self, app_ids: List[PydanticObjectId]
    ):
        applications = {
            a.id
            for a in await Application.find(In("_id", app_ids))
            .project(IdProjection)
            .to_list()
        }
        new_applications = applications.difference(self._application_events)
        for app_id in new_applications:
            await self.connection.add_to_group(CG.application_events(app_id))
        self._application_events = self._application_events.union(
            new_applications
        )
        await self._sync()

    @bind_message("set_application_subscription")
    async def set_application_subscription(
        self, app_id: Optional[PydanticObjectId]
    ):
        if self._subscribed_application == app_id:
            return
        if self._subscribed_application:
            await self.connection.remove_from_group(
                CG.monitoring.app(self._subscribed_application)
            )
        if app_id:
            await self.connection.add_to_group(CG.monitoring.app(app_id))
        self._subscribed_application = app_id

    async def _sync(self):
        await self.send_message(
            "sync",
            {
                "application_events": list(self._application_events),
            },
        )
