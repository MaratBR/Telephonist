import enum
from datetime import datetime
from typing import Optional, List, Dict

from beanie import Document, PydanticObjectId, Indexed
from pydantic import Field, BaseModel

from server.auth.models import TokenSubjectMixin
from server.auth.tokens import static_token_factory
from server.database import register_model


class HostSoftware(BaseModel):
    version: Optional[str]
    name: str


class SendDataIf(enum.Enum):
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
class ApplicationHost(Document, TokenSubjectMixin):
    name: str
    software: Optional[HostSoftware] = None
    last_active: Optional[datetime] = None
    server_id: Optional[PydanticObjectId]
    server_ip: Optional[str]
    is_online: bool = False
    pid: Optional[int] = None
    local_config: Optional[LocalConfig] = None
    local_config_rev: Optional[datetime] = None
    token: Indexed(str, unique=True) = Field(default_factory=static_token_factory(prefix='appHost'))

    class Settings:
        use_revision = True

    class Collection:
        name = 'application_hosts'

