from typing import Any, Dict, Optional
from uuid import UUID

from beanie import PydanticObjectId

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import CG


async def on_new_application_settings(
    app_id: PydanticObjectId, new_settings: Dict[str, Any], *, stamp: Optional[UUID] = None
):
    await get_channel_layer().groups_send(
        [CG.app(app_id), CG.entry("application", app_id)],
        "settings_update",
        {"settings": new_settings},
    )
