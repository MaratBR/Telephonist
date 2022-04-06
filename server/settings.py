import enum
import inspect
from datetime import timedelta
from typing import List, Optional, Type, Union

from pydantic import BaseSettings, SecretStr


class Settings(BaseSettings):
    # database and other connections
    mongodb_db_name: str = "telephonist"
    db_url: Optional[str] = "mongodb://127.0.0.1:27017"
    redis_url: Optional[str] = "redis://127.0.0.1:6379"
    session_redis_url: Optional[str] = None
    messaging_redis_url: Optional[str] = None

    # authentication, secret, access control
    secret: SecretStr
    jwt_issuer: Optional[str] = "https://telephonist.io"
    session_lifetime: timedelta = timedelta(days=30)
    cors_origin: List[str] = []

    class SessionBackend(str, enum.Enum):
        MEMORY = "memory"
        REDIS = "redis"

    session_backend: SessionBackend = SessionBackend.REDIS

    class BackplaneBackend(str, enum.Enum):
        REDIS = "redis"
        MEMORY = "memory"

    backplane_backend: BackplaneBackend = BackplaneBackend.REDIS

    # database population
    default_username: str = "admin"
    default_password: str = "admin"

    # other
    user_registration_unix_socket_only: bool = True
    unix_socket_name: str = "unix"
    hanging_connections_policy: str = "remove"
    cookies_policy: str = "None"
    use_non_secure_cookies: bool = False
    use_capped_collection_for_logs: bool = True
    logs_capped_collection_max_size_mb: int = 2**16  # 2**16 mb == 64 GiB
    root_path: str = "/api/v1"
    is_testing: bool = False

    class Config:
        env_prefix = "telephonist_"
        env_file = ".env"


class DebugSettings(Settings):
    cors_origin: List[str] = [
        "http://localhost:8080",
        "http://localhost:5500",
        "http://telephonist.lc:8080",
        "http://localhost.localdomain:8080",
    ]
    secret: SecretStr = "secret" * 5

    class Config:
        env_prefix = "telephonist_"
        env_file = ".env"


class TestingSettings(Settings):
    secret: SecretStr = "secret" * 5
    backplane_backend = Settings.BackplaneBackend.MEMORY
    session_backend = Settings.SessionBackend.MEMORY
    is_testing = True


_settings: Optional[Settings] = None


def get_settings():
    assert _settings is not None, "settings has not been initialized yet"
    return _settings


def use_settings(new_settings: Union[Settings, Type[Settings]]):
    global _settings
    assert _settings is None, "settings has already been initialized"
    if inspect.isclass(new_settings):
        _settings = new_settings()
    else:
        _settings = new_settings
