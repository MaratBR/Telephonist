import enum
from datetime import datetime
from typing import Optional, List, Dict

from beanie import Document, PydanticObjectId
from pydantic import Field, BaseModel

from server.database import register_model
from server.internal.auth.utils import static_key_factory


class HostSoftware(BaseModel):
    version: Optional[str]
    name: str


class SendDataIf(str, enum.Enum):
    ALWAYS = 'always'
    NEVER = 'never'
    IF_NON_ZERO_EXIT_CODE = 'if_non_0_exit_code'


class HostedApplication(BaseModel):
    name: str
    command: str
    env: Optional[Dict[str, str]]
    send_stderr: SendDataIf = SendDataIf.ALWAYS
    send_stdout: SendDataIf = SendDataIf.IF_NON_ZERO_EXIT_CODE
    run_on: Optional[List[str]]
    cron_cfg: Optional[str]


class LocalConfig(BaseModel):
    hosted_applications: Dict[PydanticObjectId, HostedApplication]


@register_model
class ApplicationHost(Document):
    name: str
    software: Optional[HostSoftware] = None
    last_active: Optional[datetime] = None
    server_ip: Optional[str]
    is_online: bool = False
    pid: Optional[int] = None
    local_config: Optional[LocalConfig] = None
    local_config_rev: Optional[datetime] = None
    access_key: str = Field(default_factory=static_key_factory(key_type='app-host'))

    @classmethod
    def find_by_key(cls, key: str):
        return cls.find_one({'access_key': key})

    class AppHostView(BaseModel):
        id: PydanticObjectId = Field(alias='_id')
        name: str
        software: Optional[HostSoftware] = None
        last_active: Optional[datetime] = None
        server_ip: Optional[str]
        is_online: bool = False
        local_config: Optional[LocalConfig] = None
        local_config_rev: Optional[datetime] = None

    class Settings:
        use_revision = True
        use_state_management = True

    class Collection:
        name = 'application_hosts'

