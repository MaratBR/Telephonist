import binascii
import secrets
import string
from functools import partial

from jose import JWTError, jwt
from passlib.context import CryptContext

from server.auth.exceptions import InvalidToken

__all__ = (
    "hash_password",
    "verify_password",
    "decode_token_raw",
    "encode_token_raw",
    "create_static_key",
    "static_key_factory",
    "parse_resource_key",
    "unmask_hex_token",
    "mask_hex_token",
    "generate_csrf_token",
)

from server.settings import settings

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
            settings.get().secret.get_secret_value(),
            issuer=settings.get().jwt_issuer,
            algorithms=[jwt.ALGORITHMS.HS256],
            options={"require_sub": True},
        )
    except JWTError as err:
        raise InvalidToken(str(err))


def encode_token_raw(data: dict):
    return jwt.encode(
        {**data, "iss": settings.get().jwt_issuer},
        settings.get().secret.get_secret_value(),
    )


_STATIC_KEY_ABC = (
    string.digits + string.ascii_uppercase + string.ascii_lowercase
)


def create_static_key(length: int):
    return "".join(secrets.choice(_STATIC_KEY_ABC) for i in range(length))


def static_key_factory(length: int = 42):
    return partial(create_static_key, length)


def parse_resource_key(key: str) -> tuple[str, str]:
    try:
        type_, id_ = key.split(".")
        return type_, id_
    except ValueError:
        raise ValueError("invalid resource key")


_CSRF_BYTES = 16


def generate_csrf_token():
    return secrets.token_hex(_CSRF_BYTES)


def mask_hex_token(token: str):
    salt = secrets.token_hex(_CSRF_BYTES)
    xored = int(token, 16) ^ int(salt, 16)
    return salt + binascii.hexlify(
        xored.to_bytes(_CSRF_BYTES, byteorder="big")
    ).decode("ascii")


def unmask_hex_token(masked_token: str):
    if len(masked_token) != _CSRF_BYTES * 4:
        raise ValueError("invalid length of the masked token")
    salt = masked_token[: _CSRF_BYTES * 2]
    xored = masked_token[_CSRF_BYTES * 2 :]
    token = int(xored, 16) ^ int(salt, 16)
    return binascii.hexlify(
        token.to_bytes(_CSRF_BYTES, byteorder="big")
    ).decode("ascii")
