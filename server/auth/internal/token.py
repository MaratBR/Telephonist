import abc
from datetime import datetime, timezone
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

import nanoid
from beanie import PydanticObjectId
from pydantic import Field, ValidationError, validator

from server.auth.internal.exceptions import InvalidToken
from server.auth.internal.utils import decode_token_raw, encode_token_raw
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
    def decode(cls: Type[T], token_string: str) -> T:
        if cls is TokenModel:
            raise RuntimeError(
                "decode method can only be called on derived classes"
            )
        return cls._decode_types(token_string, allowed_types=[cls])

    def token_dict(self):
        return self.dict(by_alias=True)

    def encode(self):
        data = self.token_dict()
        data["__token_type"] = self.__class__.__token_type__
        return encode_token_raw(data)

    @classmethod
    def _decode_types(
        cls, token_string: str, allowed_types: Union[List[Type["TokenModel"]]]
    ) -> "TokenModel":
        allowed_types = [t.__token_type__ for t in allowed_types]
        data = decode_token_raw(token_string)
        token_type = data.get("__token_type", "")
        if token_type is not None:
            del data["__token_type"]
        if token_type not in cls.registry:
            raise InvalidToken("invali token task_type: " + token_type)
        if allowed_types and token_type not in allowed_types:
            raise InvalidToken("disallowed token task_type: " + token_type)
        class_ = cls.registry[token_type]

        try:
            return class_(**data)
        except ValidationError as err:
            raise InvalidToken(str(err))


TModel = TypeVar("TModel", bound=TokenModel)


if TYPE_CHECKING:

    class JWT(Generic[TModel]):
        model: TModel

else:

    class JWTWrapper(str):
        __model_type__: Type[TokenModel]

        def __new__(cls, value: str, __model=None):
            o = str.__new__(cls, value)
            if __model is None:
                __model = cls.__model_type__.decode(value)
            o.model = __model
            return o

        @classmethod
        def validate(cls, value: str):
            if len(value.split(".")) != 3:
                raise ValueError("invalid token format: must have 3 segments")
            return cls(value)

        @classmethod
        def __get_validators__(cls):
            yield cls.validate

    class JWTMeta(type):
        def __getitem__(self, item: Type[TokenModel]):
            return type(
                f"JWT[{item.__name__}]",
                (JWTWrapper,),
                {"__model_type__": item},
            )

    class JWT(metaclass=JWTMeta):
        pass


class UserTokenBase(TokenModel, abc.ABC):
    sub: PydanticObjectId

    @validator("sub")
    def _stringify_sub(cls, v):
        return str(v)


class PasswordResetToken(UserTokenBase):
    __token_type__ = "password-reset"


class UserTokenModel(UserTokenBase):
    __token_type__ = ""  # default token task_type
    jti: str = Field(default_factory=nanoid.generate)
    nbf: datetime = Field(default_factory=datetime.utcnow)
    is_superuser: bool
    username: str
    check_string: Optional[str]
