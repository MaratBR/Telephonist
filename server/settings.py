from datetime import timedelta
from typing import List, Optional

from pydantic import BaseSettings


class Settings(BaseSettings):
    mongodb_db_name: str = "telephonist"
    db_url: Optional[str] = "mongodb://127.0.0.1:27017"

    secret: str = "secret" * 5
    jwt_issuer: Optional[str] = "https://telephonist.io"
    session_lifetime: timedelta = timedelta(days=30)
    rotate_refresh_token: bool = True
    redis_url: Optional[str] = "redis://127.0.0.1:6379"
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
    hanging_connections_policy: str = "remove"
    cookies_policy: str = "Strict"
    use_non_secure_cookies: bool = False
    use_capped_collection_for_logs: bool = True
    logs_capped_collection_max_size_mb: int = 2**16  # 2**16 mb == 64 GiB
    root_path: str = "/api/v1"

    class Config:
        env_prefix = "telephonist_"
        env_file = ".env"


settings = Settings()
