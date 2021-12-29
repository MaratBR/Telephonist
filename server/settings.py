from datetime import timedelta
from typing import List, Optional

from pydantic import BaseSettings


class Settings(BaseSettings):
    mongodb_db_name: str = "test"
    jwt_secret: str = "secret" * 5
    jwt_issuer: Optional[str] = "https://telephonist.io"
    refresh_token_lifetime: timedelta = timedelta(days=30)
    rotate_refresh_token: bool = True
    redis_url: Optional[str] = "redis://127.0.0.1:6379"
    db_url: str = "mongodb://localhost:27017"
    is_testing: bool = False
    cors_origin: List[str] = ["http://localhost:1234", "https://localhost:1234"]
    default_username: str = "admin"
    default_password: str = "admin"
    create_default_user: bool = True
    user_registration_unix_socket_only: bool = True
    unix_socket_name: str = "unix"
    use_anonymous_user: bool = False

    class Config:
        env_prefix = "telephonist_"
        env_file = ".env"


settings = Settings()
