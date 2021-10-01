from typing import List, Optional

from pydantic import BaseSettings


class Settings(BaseSettings):
    mongodb_connection_string: str = 'mongodb://localhost:27017'
    mongodb_db_name: str = 'test'

    jwt_secret_token: str = 'secret'
    jwt_issuer: Optional[str] = None

    redis_url: Optional[str] = 'redis://localhost:6379'
    use_local_messaging: bool = True

    db_url: str = 'mongodb://localhost:27017'


settings = Settings()
