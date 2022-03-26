from datetime import datetime
from typing import Optional

from server.common.models import BaseDocument
from server.database.registry import register_model


@register_model
class PersistentSession(BaseDocument):
    id: str
    session: dict
    last_used: Optional[datetime]
