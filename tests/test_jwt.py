from datetime import datetime, timezone

from beanie import Document, PydanticObjectId

from server.auth.token import TokenModel
from server.common.channels import WSTicketModel


def test_ticket():
    class Doc(Document):
        ...

    ticket_class = WSTicketModel[Doc]
    ticket = ticket_class(sub=PydanticObjectId(), exp=datetime.now())
    assert isinstance(ticket.sub, PydanticObjectId)

    ticket.encode()
    ticket_class.decode(ticket.encode())


def test_jwt():
    class Model(TokenModel):
        sub: str
        test: int

    model = Model(
        sub="hello",
        test=42,
        exp=datetime.utcnow().replace(microsecond=0, tzinfo=timezone.utc),
    )
    jwt = model.encode()
    new_model = Model.decode(jwt)
    assert new_model == model
