from datetime import datetime, timezone

from beanie import Document, PydanticObjectId

from server.auth.services import TokenService
from server.auth.token import TokenModel
from server.common.channels import WSTicketModel


def test_ticket(settings):
    class Doc(Document):
        ...

    token_service = TokenService(settings)
    ticket_class = WSTicketModel[Doc]
    ticket = ticket_class(
        sub=PydanticObjectId(),
        exp=datetime.utcnow().replace(microsecond=0, tzinfo=timezone.utc),
    )
    assert isinstance(ticket.sub, PydanticObjectId)

    encoded = token_service.encode(ticket)
    decoded = token_service.decode(ticket_class, encoded)
    assert decoded == ticket


def test_jwt(settings):
    class Model(TokenModel):
        sub: str
        test: int

    token_service = TokenService(settings)
    model = Model(
        sub="hello",
        test=42,
        exp=datetime.utcnow().replace(microsecond=0, tzinfo=timezone.utc),
    )
    jwt = token_service.encode(model)
    new_model = token_service.decode(Model, jwt)
    assert new_model == model
