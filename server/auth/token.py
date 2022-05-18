import abc
from datetime import datetime, timezone
from typing import ClassVar, Type, TypeVar

import nanoid
from beanie import PydanticObjectId
from pydantic import Field, validator

from server.common.models import AppBaseModel

T = TypeVar("T", bound="TokenModel")


class TokenModel(AppBaseModel):
    __token_type__: ClassVar[str]
    registry: ClassVar[dict[str, Type["TokenModel"]]] = {}
    exp: datetime
    iat: datetime = Field(
        default_factory=lambda: datetime.utcnow().replace(
            microsecond=0, tzinfo=timezone.utc
        )
    )
    jti: str = Field(default_factory=nanoid.generate)

    def __init_subclass__(cls, **kwargs):
        if not isinstance(cls, abc.ABC):
            if not hasattr(cls, "__token_type__"):
                setattr(cls, "__token_type__", cls.__name__)
            TokenModel.registry[cls.__token_type__] = cls
        return super(TokenModel, cls).__init_subclass__(**kwargs)

    @classmethod
    def decode(
        cls: Type[T], token_string: str, secret_key: str, issuer: str
    ) -> T:
        if cls is TokenModel:
            raise RuntimeError(
                "decode method can only be called on derived classes"
            )
        return cls._decode_types(
            token_string,
            allowed_types=[cls],
        )

    def token_dict(self):
        return self.dict(by_alias=True)


class UserTokenBase(TokenModel, abc.ABC):
    sub: PydanticObjectId

    @validator("sub")
    def _stringify_sub(cls, v):
        return str(v)


class PasswordResetToken(UserTokenBase):
    __token_type__ = "password-reset"
