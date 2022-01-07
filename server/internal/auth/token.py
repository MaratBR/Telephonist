from datetime import datetime
from typing import ClassVar, Dict, List, Optional, Type, TypeVar, Union

import nanoid
from beanie import PydanticObjectId
from jose import JWTError
from pydantic import BaseModel, Field, ValidationError, root_validator

from server.internal.auth import decode_token_raw
from server.internal.auth.exceptions import AuthError, InvalidToken

T = TypeVar("T", bound="TokenModel")


class TokenModel(BaseModel):
    __token_type__: ClassVar[str]
    registry: ClassVar[Dict[str, Type["TokenModel"]]]
    exp: datetime
    iat: datetime = Field(default_factory=datetime.now)

    def __init_subclass__(cls, **kwargs):
        if not hasattr(cls, "__token_type__"):
            setattr(cls, "__token_type__", cls.__name__)
        TokenModel.registry[cls.__token_type__] = cls

    @root_validator(pre=True)
    def _maybe_parse(cls, value):
        if isinstance(value, str):
            value = decode_token_raw(value)
            token_type = value.pop("__token_type")
            assert token_type != cls.__token_type__, (
                "Invalid token type, required token type: " + cls.__token_type__
            )
        return value

    @classmethod
    def decode(cls: Type[T], token_string: str) -> T:
        if cls is TokenModel:
            raise RuntimeError("decode method can only be called on derived classes")
        return cls._decode_types(token_string, allowed_types=[cls])

    @classmethod
    def _decode_types(
        cls, token_string: str, allowed_types: Union[List[Type["TokenModel"]]]
    ) -> "TokenModel":
        data = decode_token_raw(token_string)
        token_type = data.get("__token_type")
        if token_type is not None:
            del data["__token_type"]
        if token_type not in cls.registry:
            raise InvalidToken("invali token type: " + token_type)
        if allowed_types and token_type not in allowed_types:
            raise InvalidToken("disallowed token type: " + token_type)
        class_ = cls.registry[token_type]

        try:
            return class_(**data)
        except ValidationError as err:
            raise InvalidToken(str(err))


class PasswordResetToken(TokenModel):
    __token_type__ = "password-reset"
    sub: PydanticObjectId


class UserTokenModel(TokenModel):
    __token_type__ = ""  # default token type
    sub: PydanticObjectId
    exp: datetime
    jti: str = Field(default_factory=nanoid.generate)
    iat: datetime = Field(default_factory=datetime.now)
    nbf: datetime = Field(default_factory=datetime.utcnow)
    is_superuser: bool
    username: str
    check_string: Optional[str]
