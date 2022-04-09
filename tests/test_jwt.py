from datetime import datetime

from beanie import Document, PydanticObjectId

from server.common.channels import WSTicketModel


def test_ticket():
    class Doc(Document):
        ...

    ticket_class = WSTicketModel[Doc]
    ticket = ticket_class(sub=PydanticObjectId(), exp=datetime.now())
    assert isinstance(ticket.sub, PydanticObjectId)

    ticket.encode()
    ticket_class.decode(ticket.encode())
