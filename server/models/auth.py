import base64
import hashlib
from datetime import datetime, timedelta
from typing import *

from beanie import Document, PydanticObjectId
from beanie.operators import Eq
from pydantic import BaseModel, EmailStr, Field, root_validator
from starlette.datastructures import Address
from starlette.requests import Request

from server.database import register_model
from server.internal.auth.token import UserTokenModel
from server.internal.auth.utils import create_static_key, hash_password, verify_password
from server.settings import settings


@register_model
class User(Document):
    username: str
    normalized_username: str
    email: Optional[EmailStr] = None
    password_hash: str
    disabled: bool = False
    password_reset_required: bool = False
    last_password_changed: Optional[datetime] = None
    is_superuser: bool = True

    def set_password(self, password: str):
        self.password_hash = hash_password(password)
        self.password_reset_required = False
        self.last_password_changed = datetime.utcnow()

    def __str__(self):
        return self.username

    def create_token(
        self,
        lifetime: timedelta,
        check_string: Optional[str] = None,
    ):
        if check_string:
            check_string = hashlib.sha256(check_string.encode()).hexdigest()
        return UserTokenModel(
            sub=self.id,
            is_superuser=self.is_superuser,
            username=self.username,
            exp=datetime.utcnow() + lifetime,
            check_string=check_string,
        )

    @classmethod
    async def find_user_by_credentials(cls, login: str, password: str):
        user = await cls.find_one(
            {"$or": [{"email": login}, {"normalized_username": login.upper()}]}
        )
        if user and verify_password(password, user.password_hash):
            return user
        return None

    @classmethod
    async def by_username(cls, username: str, include_disabled: bool = False) -> Optional["User"]:
        q = cls if include_disabled else cls.find(cls.disabled == False)
        q = cls.find(cls.username == username)
        q = q.limit(1)
        results = await q.to_list()
        if len(results) == 0:
            return None
        return results[0]

    @classmethod
    async def create_user(
        cls,
        username: str,
        password: str,
        email: Optional[EmailStr] = None,
        password_reset_required: bool = False,
    ):
        user = cls(
            username=username,
            normalized_username=username.upper(),
            display_name=username,
            password_hash=hash_password(password),
            email=email,
            password_reset_required=password_reset_required,
        )
        await user.save()
        return user

    @classmethod
    async def on_database_ready(cls):
        if not await cls.find(
            cls.normalized_username == settings.default_username.upper()
        ).exists():
            await cls.create_user(
                settings.default_username, settings.default_password, password_reset_required=True
            )

    @classmethod
    async def anonymous(cls):
        user = await cls.by_username("Anonymous")
        if user is None:
            user = User(username="Anonymous", password_hash="")
            await user.save()
        return user

    class Settings:
        use_state_management = True

    class Collection:
        name = "users"
        indexes = ["email", "disabled", "normalized_username"]


class UserView(BaseModel):
    username: str
    disabled: bool
    id: PydanticObjectId = Field(alias="_id")
    email: Optional[str]
    is_superuser: bool

    @root_validator
    def _root_validator(cls, value: dict) -> dict:
        value["created_at"] = value["id"].generation_time
        return value


@register_model
class BlockedAccessToken(Document):
    id: str
    blocked_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    async def block(cls, token_id: str):
        if await cls.is_blocked(token_id):
            return
        blocked_token = cls(id=token_id)
        await blocked_token.save()

    @classmethod
    async def is_blocked(cls, token_id: str) -> bool:
        return await cls.find(cls.id == token_id).count() > 0


@register_model
class RefreshToken(Document):
    id: str
    expiration_date: datetime
    blocked: bool = False
    last_used: Optional[datetime] = None
    user_id: PydanticObjectId

    @classmethod
    async def is_blocked(cls, token: str) -> bool:
        return await cls.find(cls.id == cls._make_token_id(token)).count() > 0

    @classmethod
    async def delete_token(cls, token: str):
        await cls.find(cls.id == cls._make_token_id(token)).delete()

    @classmethod
    async def find_valid(cls, token: str) -> Optional["RefreshToken"]:
        return await cls.find_one(
            cls.id == cls._make_token_id(token),
            Eq(cls.blocked, False),
            cls.expiration_date > datetime.utcnow(),
        )

    @classmethod
    async def create_token(cls, user: User, lifetime: timedelta) -> Tuple["RefreshToken", str]:
        token = create_static_key(40)
        refresh_token = cls(
            user_id=user.id,
            expiration_date=datetime.utcnow() + lifetime,
            id=cls._make_token_id(token),
        )
        await refresh_token.save()
        return refresh_token, token

    def matches(self, token: str):
        return self.id == base64.urlsafe_b64encode(hashlib.sha256(token).digest())[:43].decode(
            "ascii"
        )

    @staticmethod
    def _make_token_id(token: str):
        digest = hashlib.sha256(token.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest)[:43].decode("ascii")


@register_model
class AuthLog(Document):
    event: str
    user_id: PydanticObjectId
    ip_address: str
    user_agent: str

    class Collection:
        name = "auth_log"

    @classmethod
    async def log(
        cls,
        event: str,
        user_id: PydanticObjectId,
        user_agent: str,
        ip_address_or_request: Union[str, Address, Request],
    ):
        if isinstance(ip_address_or_request, Request):
            address = ip_address_or_request.client.host
        elif isinstance(ip_address_or_request, Address):
            address = ip_address_or_request.host
        else:
            address = ip_address_or_request
        await cls(user_agent=user_agent, event=event, user_id=user_id, ip_address=address).insert()
