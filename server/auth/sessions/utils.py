import binascii
import secrets

_CSRF_BYTES = 20


def generate_csrf_token():
    return secrets.token_hex(_CSRF_BYTES)


def mask_csrf_token(token: str):
    salt = secrets.token_hex(_CSRF_BYTES)
    xored = int(token, 16) ^ int(salt, 16)
    return salt + binascii.hexlify(
        xored.to_bytes(_CSRF_BYTES, byteorder="big")
    ).decode("ascii")


def unmask_token(masked_token: str):
    if len(masked_token) != _CSRF_BYTES * 4:
        raise ValueError("invalid length of the masked token")
    salt = masked_token[: _CSRF_BYTES * 2]
    xored = masked_token[_CSRF_BYTES * 2 :]
    token = int(xored, 16) ^ int(salt, 16)
    return binascii.hexlify(
        token.to_bytes(_CSRF_BYTES, byteorder="big")
    ).decode("ascii")
