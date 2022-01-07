import secrets
from datetime import timedelta
from typing import *

import branca
import msgpack
from beanie import PydanticObjectId
from jose import JWTError, jwt
from passlib.context import CryptContext

from server.internal.auth.exceptions import InvalidToken
from server.settings import settings

__all__ = (
    "hash_password",
    "verify_password",
    "decode_token_raw",
    "encode_token_raw",
    "create_resource_key",
    "resource_key_factory",
    "parse_resource_key",
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def decode_token_raw(token: str) -> dict:
    """
    :param token: токен
    :return: словарь с данными токена
    """
    try:
        return jwt.decode(
            token,
            settings.secret,
            issuer=settings.jwt_issuer,
            algorithms=[jwt.ALGORITHMS.HS256],
            options={"require_sub": True},
        )
    except JWTError as err:
        raise InvalidToken(str(err))


def encode_token_raw(data: dict):
    return jwt.encode(
        {**data, "iss": settings.jwt_issuer},
        settings.secret,
    )


def create_resource_key(length: int = 20, token_type: Optional[str] = None):
    tok = secrets.token_urlsafe(length)
    if token_type is not None:
        tok = token_type + "." + tok
    return tok


def resource_key_factory(length: int = 12, key_type: Optional[str] = None):
    def _token_factory_function():
        return create_resource_key(length, key_type)

    return _token_factory_function


def parse_resource_key(key: str) -> Tuple[str, str]:
    try:
        type_, id_ = key.split(".")
        return type_, id_
    except ValueError:
        raise ValueError("invalid resource key")
