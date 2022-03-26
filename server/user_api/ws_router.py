import asyncio
from datetime import datetime, timedelta
from typing import List, Set, Union

from fastapi import APIRouter, Depends

from server import VERSION
from server.auth.internal.dependencies import get_session
from server.auth.internal.sessions import UserSession
from server.auth.models.auth import User
from server.common.channels import WSTicket, WSTicketModel
from server.common.channels.hub import Hub, bind_message, ws_controller
from server.common.internal.utils import CG
from server.ws_root_router import ws_root_router

ws_router = APIRouter()


@ws_router.get("/issue-ws-ticket")
async def issue_user_ws_ticket(token: UserSession = Depends(get_session)):
    exp = datetime.now() + timedelta(minutes=5)
    return {
        "ticket": WSTicketModel[User](exp=exp, sub=token.user_id).encode(),
        "exp": exp,
    }


@ws_controller(ws_root_router, "/_ws/user-api/main")
class UserHub(Hub):
    ticket: WSTicketModel[User] = WSTicket(User)

    def __init__(self):
        self._topics_lock = asyncio.Lock()
        super().__init__()
        self._topics: Set[str] = set()

    async def on_connected(self):
        await self.connection.add_to_group(CG.AUTH / "user" / self.ticket.sub)
        await self.send_message(
            "introduction", {"server_version": VERSION, "authentication": "ok"}
        )

    @bind_message("set_topics")
    async def set_topics(self, topics: List[str]):
        new_topics = set()
        for t in topics:
            if not CG.MONITORING.is_parent_of(t):
                continue
            new_topics.add(t)
            if t not in self._topics:
                await self.connection.add_to_group(t)

        for t in self._topics:
            if t not in new_topics:
                await self.connection.remove_from_group(t)
        self._topics = new_topics
        await self._sync()

    @bind_message("sub")
    async def subscribe_to_topic(self, topic: Union[List[str], str]):
        if isinstance(topic, str):
            topic = [topic]
        for t in topic:
            if not CG.MONITORING.is_parent_of(t):
                continue
            if t in self._topics or t.strip() == "":
                continue
            self._topics.add(t)
            await self.connection.add_to_group(t)
        await self._sync()

    @bind_message("unsub")
    async def unsubscribe_from_topic(self, topic: Union[List[str], str]):
        if isinstance(topic, str):
            topic = [topic]
        for t in topic:
            if t not in self._topics or t.strip() == "":
                continue
            self._topics.remove(t)
            await self.connection.remove_from_group(CG.MONITORING / t)
        await self._sync()

    @bind_message("unsuball")
    async def unsub_from_all_topics(self):
        for t in self._topics:
            await self.connection.remove_from_group(CG.MONITORING / t)
        await self._sync()

    @bind_message("sync")
    async def _sync(self):
        await self.send_message(
            "sync",
            {
                "topics": list(self._topics),
            },
        )
