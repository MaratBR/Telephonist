import secrets
from typing import *

from jose import jwt
from passlib.context import CryptContext

from server.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def decode_token(token: str) -> dict:
    """
    :raises JWTError: If the signature is invalid in any way.
    :raises ExpiredSignatureError: If the signature has expired.
    :raises JWTClaimsError: If any claim is invalid in any way.

    :param token: токен
    :return: словарь с данными токена
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        issuer=settings.jwt_issuer,
        algorithms=[jwt.ALGORITHMS.HS256],
        options={"require_sub": True},
    )


def encode_token(data: dict):
    return jwt.encode(
        {**data, "iss": settings.jwt_issuer},
        settings.jwt_secret,
    )


def create_static_key(length: int = 20, token_type: Optional[str] = None):
    tok = secrets.token_urlsafe(length)
    if token_type is not None:
        tok = token_type + "." + tok
    return tok


def static_key_factory(length: int = 12, key_type: Optional[str] = None):
    def _token_factory_function():
        return create_static_key(length, key_type)

    return _token_factory_function