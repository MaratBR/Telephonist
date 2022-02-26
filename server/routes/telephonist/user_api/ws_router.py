from datetime import datetime, timedelta
from typing import List, Set, Union

from fastapi import APIRouter

from server import VERSION
from server.internal.auth.dependencies import AccessToken
from server.internal.channels import WSTicket, WSTicketModel
from server.internal.channels.hub import Hub, bind_message, ws_controller
from server.internal.telephonist import CG
from server.models.auth import User

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
        self._topics: Set[str] = set()

    async def on_connected(self):
        await self.connection.add_to_group(CG.auth.user(self.ticket.sub))
        await self.send_message(
            "introduction", {"server_version": VERSION, "authentication": "ok"}
        )

    @bind_message("sub")
    async def subscribe_to_topic(self, topic: Union[List[str], str]):
        if isinstance(topic, str):
            topic = [topic]
        for t in topic:
            if t in self._topics or t.strip() == "":
                continue
            self._topics.add(t)
            await self.connection.add_to_group(CG.monitoring(t))
        await self._sync()

    @bind_message("unsub")
    async def unsubscribe_from_topic(self, topic: Union[List[str], str]):
        if isinstance(topic, str):
            topic = [topic]
        for t in topic:
            if t not in self._topics or t.strip() == "":
                continue
            self._topics.remove(t)
            await self.connection.remove_from_group(CG)
        await self._sync()

    @bind_message("unsuball")
    async def unsub_from_all_topics(self):
        for t in self._topics:
            await self.connection.remove_from_group(CG.monitoring(t))

    @bind_message("sync")
    async def _sync(self):
        await self.send_message(
            "sync",
            {
                "topics": list(self._topics),
            },
        )
