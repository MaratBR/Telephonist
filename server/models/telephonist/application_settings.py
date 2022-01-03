from typing import Dict, List, Optional, Type

from pydantic import BaseModel, Field

from server.models.telephonist import Application


class TaskDescriptor(BaseModel):
    cmd: Optional[str]
    on_events: List[str]
    cron: Optional[str]
    env: Dict[str, str]
    task_name: str


class HostSettings(BaseModel):
    tasks: List[TaskDescriptor] = Field(default_factory=list)


def get_default_settings_for_type(application_type: str):
    model_class = get_application_settings_model(application_type)
    if model_class:
        return model_class()


def get_application_settings_model(application_type: str) -> Type[BaseModel]:
    if application_type == Application.HOST_TYPE:
        return HostSettings


def application_type_allows_empty_settings(application_type: str):
    return application_type not in (Application.HOST_TYPE,)
