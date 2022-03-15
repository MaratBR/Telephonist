from datetime import timedelta
from typing import List, Optional

from pydantic import BaseSettings


class Settings(BaseSettings):
    mongodb_db_name: str = "telephonist"
    secret: str = "secret" * 5
    jwt_issuer: Optional[str] = "https://telephonist.io"
    session_lifetime: timedelta = timedelta(days=30)
    rotate_refresh_token: bool = True
    redis_url: Optional[str] = "redis://127.0.0.1:6379"
    db_url: Optional[str] = "mongodb://127.0.0.1:27017"
    is_testing: bool = False
    cors_origin: List[str] = [
        "http://localhost:8080",
        "http://localhost:5500",
        "http://telephonist.lc:8080",
        "http://localhost.localdomain:8080",
    ]
    default_username: str = "admin"
    default_password: str = "admin"
    user_registration_unix_socket_only: bool = True
    unix_socket_name: str = "unix"
    use_anonymous_user: bool = False
    hanging_connections_policy: str = "remove"
    cookies_policy: str = "None"
    use_capped_collection_for_logs: bool = True
    logs_capped_collection_max_size_mb: int = 2**16  # 2**15 mb == 64 GiB

    class Config:
        env_prefix = "telephonist_"
        env_file = ".env"


settings = Settings()
