from typing import List, Optional

from pydantic import Field

from server.common.models import AppBaseModel


class TaskDescriptor(AppBaseModel):
    cmd: Optional[str]
    on_events: List[str]
    cron: Optional[str]
    env: dict[str, str]
    task_name: str


class HostSettings(AppBaseModel):
    tasks: List[TaskDescriptor] = Field(default_factory=list)
