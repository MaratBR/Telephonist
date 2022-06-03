from datetime import datetime
from typing import Any, Optional, Union
from uuid import UUID, uuid4

import pymongo
from beanie import Document, Indexed, PydanticObjectId
from pydantic import EmailStr, Field, root_validator
from starlette.datastructures import Address
from starlette.requests import Request

from server.common.models import AppBaseModel, BaseDocument
from server.database.registry import register_model

from .utils import generate_csrf_token

__all__ = (
    "User",
    "UserSession",
    "AuthLog",
    "UserView",
)


@register_model
class User(BaseDocument):
    username: str
    normalized_username: str
    email: Optional[EmailStr] = None
    password_hash: str
    disabled: bool = False
    password_reset_required: bool = False
    last_password_changed: Optional[datetime] = None
    is_superuser: bool = True
    is_blocked: bool = False
    blocked_at: Optional[datetime] = None
    will_be_deleted_at: Optional[datetime]

    def __str__(self):
        return self.username

    @classmethod
    async def by_username(
        cls, username: str, include_disabled: bool = False
    ) -> Optional["User"]:
        q = cls if include_disabled else cls.find(cls.disabled == False)
        q = q.find(cls.username == username)
        q = q.limit(1)
        results = await q.to_list()
        if len(results) == 0:
            return None
        return results[0]

    @classmethod
    async def create_user(
        cls,
        username: str,
        password_hash: str,
        email: Optional[EmailStr] = None,
        password_reset_required: bool = False,
        is_superuser: bool = True,
    ):
        user = cls(
            username=username,
            normalized_username=username.upper(),
            display_name=username,
            password_hash=password_hash,
            email=email,
            password_reset_required=password_reset_required,
            is_superuser=is_superuser,
        )
        await user.save()
        return user

    async def block(self):
        if self.is_blocked:
            return
        self.is_blocked = True
        self.blocked_at = datetime.utcnow()
        await self.save()

    class Settings:
        use_state_management = True

    class Collection:
        name = "users"
        indexes = [
            "email",
            "disabled",
            pymongo.IndexModel("normalized_username", unique=True),
            pymongo.IndexModel("will_be_deleted_at", expireAfterSeconds=0),
        ]


class UserView(AppBaseModel):
    username: str
    disabled: bool
    id: PydanticObjectId = Field(alias="_id")
    email: Optional[str]
    is_superuser: bool
    is_blocked: bool = False
    will_be_deleted_at: Optional[datetime]

    @root_validator
    def _root_validator(cls, value: dict) -> dict:
        value["created_at"] = value["id"].generation_time
        return value


@register_model
class AuthLog(Document):
    event: str
    user_id: PydanticObjectId
    ip_address: str
    user_agent: str
    extra: dict[str, Any] = Field(default_factory=dict)

    class Collection:
        name = "auth_log"

    @classmethod
    async def log(
        cls,
        event: str,
        user_id: PydanticObjectId,
        user_agent: str,
        ip_address_or_request: Union[str, Address, Request],
        extra: Optional[dict[str, Any]] = None,
    ):
        if isinstance(ip_address_or_request, Request):
            address = ip_address_or_request.client.host
        elif isinstance(ip_address_or_request, Address):
            address = ip_address_or_request.host
        else:
            address = ip_address_or_request
        await cls(
            user_agent=user_agent,
            event=event,
            user_id=user_id,
            ip_address=address,
            extra=extra or {},
        ).insert()


@register_model
class UserSession(BaseDocument):
    id: str
    ref_id: Indexed(UUID, unique=True) = Field(default_factory=uuid4)
    user_id: PydanticObjectId
    user_agent: Optional[str] = None
    logged_in_at: datetime = Field(default_factory=datetime.now)
    ip_address: str
    csrf_token: str = Field(default_factory=generate_csrf_token)
    is_superuser: bool = False
    expires_at: datetime
    renew_at: Optional[datetime]

    class Collection:
        name = "sessions"
        indexes = [
            pymongo.IndexModel(
                "expires_at", name="expires_at_ttl", expireAfterSeconds=0
            )
        ]
