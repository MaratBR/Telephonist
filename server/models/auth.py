import base64
import hashlib
from datetime import datetime, timedelta
from typing import *

import nanoid
from beanie import Document, Indexed, PydanticObjectId
from beanie.operators import Eq
from pydantic import BaseModel, EmailStr, Field, root_validator, validator
from pymongo.errors import DuplicateKeyError

from server.database import register_model
from server.internal.auth.utils import (
    create_static_key,
    decode_token,
    encode_token,
    hash_password,
    verify_password,
)
from server.settings import settings


class TokenModel(BaseModel):
    sub: PydanticObjectId
    exp: datetime
    jti: str = Field(default_factory=nanoid.generate)
    iat: datetime = Field(default_factory=datetime.now)
    nbf: datetime = Field(default_factory=datetime.utcnow)
    is_superuser: bool
    token_type: str
    username: str
    check_string: Optional[str]

    @validator("sub")
    def _sub_to_str(cls, value: PydanticObjectId):
        return str(value)

    def encode(self) -> str:
        return encode_token(self.dict())

    @classmethod
    def decode(cls, token: str):
        data = decode_token(token)
        return cls(**data)


@register_model
class User(Document):
    username: Indexed(str, unique=True)
    email: Optional[EmailStr] = None
    password_hash: str
    disabled: bool = False
    password_reset_required: bool = False
    last_password_changed: Optional[datetime] = None
    is_superuser: bool = True

    def set_password(self, password: str):
        self.password_hash = hash_password(password)
        self.password_reset_required = False
        self.last_password_changed = datetime.now()

    def __str__(self):
        return self.username

    def create_token(
        self,
        token_type: str = "access",
        lifetime: Optional[timedelta] = None,
        check_string: Optional[str] = None,
    ):
        if check_string:
            check_string = hashlib.sha256(check_string.encode()).hexdigest()
        return TokenModel(
            sub=self.id,
            token_type=token_type,
            is_superuser=self.is_superuser,
            username=self.username,
            exp=datetime.now() + (lifetime or timedelta(hours=4)),
            check_string=check_string,
        )

    @classmethod
    async def find_user_by_credentials(cls, login: str, password: str):
        user = await cls.find_one({"$or": [{"email": login}, {"username": login}]})
        if user and verify_password(password, user.password_hash):
            return user
        return None

    @classmethod
    async def by_username(
        cls, username: str, include_disabled: bool = False
    ) -> Optional["User"]:
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
            password_hash=hash_password(password),
            email=email,
            password_reset_required=password_reset_required,
        )
        await user.save()
        return user

    @classmethod
    async def on_database_ready(cls):
        if settings.create_default_user:
            try:
                await cls.create_user(
                    settings.default_username, settings.default_password
                )
            except DuplicateKeyError:
                pass

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
        indexes = ["email", "disabled"]


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
    blocked_at: datetime = Field(default_factory=datetime.now)

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
    async def find_valid(cls, token: str) -> Optional["RefreshToken"]:
        return await cls.find_one(
            cls.id == cls._make_token_id(token),
            Eq(cls.blocked, False),
            cls.expiration_date > datetime.now(),
        )

    @classmethod
    async def create_token(
        cls, user: User, lifetime: timedelta
    ) -> Tuple["RefreshToken", str]:
        token = create_static_key(40)
        refresh_token = cls(
            user_id=user.id,
            expiration_date=datetime.now() + lifetime,
            id=cls._make_token_id(token),
        )
        await refresh_token.save()
        return refresh_token, token

    def matches(self, token: str):
        return self.id == base64.urlsafe_b64encode(hashlib.sha256(token).digest())[
            :43
        ].decode("ascii")

    @staticmethod
    def _make_token_id(token: str):
        digest = hashlib.sha256(token.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest)[:43].decode("ascii")
