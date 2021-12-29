import enum
from typing import *

from pydantic import BaseModel

from server.internal.telephonist.application_settings_registry import (
    builtin_application_settings,
)


class SendIf(str, enum.Enum):
    ALWAYS = "always"
    IF_NON_0_EXIT = "if_non_0_exit"
    NEVER = "never"


class TaskDescriptorType(str, enum.Enum):
    CRON = "cron"
    EVENT = "event"


class TaskDescriptor(BaseModel):
    command: Optional[str]
    send_stderr: SendIf = SendIf.ALWAYS
    send_stdout: SendIf = SendIf.ALWAYS
    on_success_event: Optional[str]
    on_failure_event: Optional[str]
    on_complete_event: Optional[str]
    cron: Optional[str]
    on_events: Optional[List[str]]


@builtin_application_settings.register("supervisor-v1")
class SupervisorSettingsV1(BaseModel):
    tasks: List[TaskDescriptor]
