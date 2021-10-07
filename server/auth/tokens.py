import secrets
from typing import Optional

from jose import jwt

from server.settings import settings


# ========================================= #
# Кодирование и декодирование JWT токенов.  #
# ========================================= #


def decode_token(token: str) -> dict:
    """
    :raises JWTError: If the signature is invalid in any way.
    :raises ExpiredSignatureError: If the signature has expired.
    :raises JWTClaimsError: If any claim is invalid in any way.

    :param token: токен
    :return: словарь с данными токена
    """
    return jwt.decode(
        token, settings.jwt_secret_token,
        issuer=settings.jwt_issuer,
        options={
            'require_sub': True
        }
    )


def encode_token(data: dict):
    return jwt.encode(data, settings.jwt_secret_token)


# ============================================= #
# Создание статических токенов (opaque token).  #
# ============================================= #

def create_static_token(length: int = 24, prefix: Optional[str] = None):
    tok = secrets.token_urlsafe(length)
    if prefix is not None:
        tok = prefix + '_' + tok
    return tok


def static_token_factory(length: int = 24, prefix: Optional[str] = None):
    def _token_factory_function():
        return create_static_token(length, prefix)

    return _token_factory_function
