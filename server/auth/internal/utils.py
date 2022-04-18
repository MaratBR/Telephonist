import base64
import hashlib
import json
import secrets
import string
from functools import partial
from typing import *

from jose import JWTError, jwt
from passlib.context import CryptContext

from server.auth.internal.exceptions import InvalidToken

__all__ = (
    "hash_password",
    "verify_password",
    "decode_token_raw",
    "encode_token_raw",
    "create_static_key",
    "static_key_factory",
    "parse_resource_key",
)

from server.settings import get_settings

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
            get_settings().secret.get_secret_value(),
            issuer=get_settings().jwt_issuer,
            algorithms=[jwt.ALGORITHMS.HS256],
            options={"require_sub": True},
        )
    except JWTError as err:
        raise InvalidToken(str(err))


def encode_token_raw(data: dict):
    return jwt.encode(
        {**data, "iss": get_settings().jwt_issuer},
        get_settings().secret.get_secret_value(),
    )


_STATIC_KEY_ABC = (
    string.digits + string.ascii_uppercase + string.ascii_lowercase
)


def create_static_key(length: int):
    return "".join(secrets.choice(_STATIC_KEY_ABC) for i in range(length))


def static_key_factory(length: int = 42):
    return partial(create_static_key, length)


def parse_resource_key(key: str) -> Tuple[str, str]:
    try:
        type_, id_ = key.split(".")
        return type_, id_
    except ValueError:
        raise ValueError("invalid resource key")


def get_client_fingerprint(
    ip_address: str, user_agent: Optional[str], extra: Optional[Any]
) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(
            json.dumps([ip_address, user_agent, extra]).encode("utf-8")
        ).digest()
    ).decode("ascii")
