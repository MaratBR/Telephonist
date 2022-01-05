import time
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from beanie import PydanticObjectId

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import ChannelGroups


async def notify_new_application_settings(
    app_id: PydanticObjectId, new_settings: Dict[str, Any], *, stamp: Optional[UUID] = None
):
    await get_channel_layer().groups_send(
        [ChannelGroups.private_app(app_id), ChannelGroups.public_app(app_id)],
        "settings_update",
        {"settings_revision": stamp, "settings": new_settings},
    )
