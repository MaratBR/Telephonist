import binascii
import secrets
import string
from functools import partial

from passlib.context import CryptContext

__all__ = (
    "create_static_key",
    "static_key_factory",
    "unmask_hex_token",
    "mask_hex_token",
    "generate_csrf_token",
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_STATIC_KEY_ABC = (
    string.digits + string.ascii_uppercase + string.ascii_lowercase
)


def create_static_key(length: int):
    return "".join(secrets.choice(_STATIC_KEY_ABC) for i in range(length))


def static_key_factory(length: int = 42):
    return partial(create_static_key, length)


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
