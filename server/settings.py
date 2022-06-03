import enum
import secrets
import warnings
from datetime import timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI
from pydantic import BaseSettings, SecretStr

__all__ = ("Settings", "DebugSettings", "TestingSettings", "get_settings")


from server.dependencies import get_application


class Settings(BaseSettings):
    # database and other connections
    mongodb_db_name: str = "telephonist"
    db_url: Optional[str] = "mongodb://127.0.0.1:27017"
    redis_url: Optional[str] = "redis://127.0.0.1:6379"

    # https
    use_https: bool = False
    ssl_key: Optional[str]
    ssl_crt: Optional[str]

    # authentication, secret, access control
    secret: SecretStr
    jwt_issuer: Optional[str] = "https://telephonist.io"
    session_lifetime: timedelta = timedelta(days=30)
    cors_origins: List[str] = []

    class BackplaneBackend(str, enum.Enum):
        REDIS = "redis"
        MEMORY = "memory"

    backplane_backend: BackplaneBackend = BackplaneBackend.REDIS

    # database population
    default_username: str = "admin"
    default_password: str = "admin"

    # other
    user_deactivation_timeout: timedelta = timedelta(days=7)
    unix_socket_name: str = "unix"
    cookies_policy: str = "Lax"
    use_capped_collection_for_logs: bool = True
    logs_capped_collection_max_size_mb: int = 2**16  # 2**16 mb == 64 GiB
    root_path: str = "/api/v1"
    is_testing: bool = False

    # spa
    spa_path: Optional[str]

    class Config:
        env_prefix = "telephonist_"
        env_file = ".env"


_generated_secret = secrets.token_urlsafe(64)


class ProductionSettings(BaseSettings):
    secret: SecretStr = _generated_secret

    def __init__(self, **kwargs):
        super(ProductionSettings, self).__init__(**kwargs)
        if self.secret == _generated_secret:
            warnings.warn(
                "Application secret key is missing. This will cause all"
                " sessions and tokens to be invalidated on each restart."
                " Please set secret key through TELEPHONIST_SECRET environment"
                " variable"
            )


class DebugSettings(Settings):
    cors_origins: List[str] = [
        "http://localhost:8080",
        "http://localhost:5500",
        "http://telephonist.lc:8080",
        "http://localhost.localdomain:8080",
    ]
    secret: SecretStr = "secret" * 5
    use_https = True
    ssl_crt = "certs/cert.crt"
    ssl_key = "certs/key.pem"

    class Config:
        env_prefix = "telephonist_"
        env_file = ".env"


class TestingSettings(Settings):
    secret: SecretStr = "secret" * 5
    backplane_backend = Settings.BackplaneBackend.MEMORY
    is_testing = True


def get_settings(app: FastAPI = Depends(get_application)) -> Settings:
    return app.state.settings
