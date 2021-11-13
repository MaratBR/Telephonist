from datetime import timedelta
from typing import Optional, List

from pydantic import BaseSettings


class Settings(BaseSettings):
    mongodb_connection_string: str = 'mongodb://localhost:27017'
    mongodb_db_name: str = 'test'

    jwt_secret_token: str = 'secret'*5
    jwt_issuer: Optional[str] = None
    refresh_token_lifetime: timedelta = timedelta(days=30)
    rotate_refresh_token: bool = True

    redis_url: Optional[str] = 'redis://localhost:6379'
    broadcaster_url: str = 'memory://'

    db_url: str = 'mongodb://localhost:27017'

    cors_origin: List[str] = ['http://localhost:3000', 'https://localhost:3000']

    class Config:
        env_prefix = 'telephonist_'
        env_file = '.env'


settings = Settings()
