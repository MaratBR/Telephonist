from typing import Optional

import uvicorn
from pydantic import BaseSettings, Field


class EnvSettings(BaseSettings):
    DISABLE_SSL: bool = False
    SSL_CERT: Optional[str]
    SSL_KEY: Optional[str]
    SSL_PASSWORD: Optional[str]
    WORKERS: int = 1
    LOG_LEVEL: str = Field(default="info")
    PORT: int = Field(default=5789, ge=1024, lt=32768)
    PROXY_IP: Optional[str] = None

    class Config:
        env_prefix = "TELEPHONIST_"


def main():
    prod_settings = EnvSettings()
    args = {}
    print(f"Running on port {prod_settings.PORT}")
    if not prod_settings.DISABLE_SSL:
        assert prod_settings.SSL_KEY and prod_settings.SSL_CERT, (
            "You must either provide ssl key path and ssl certificate through"
            " TELEPHONIST_SSL_KEY and TELEPHONIST_SSL_CERT env. variables or"
            " set TELEPHONIST_DISABLE_SSL to True"
        )
        args.update(
            ssl_keyfile=prod_settings.SSL_KEY,
            ssl_certfile=prod_settings.SSL_CERT,
            ssl_keyfile_password=prod_settings.SSL_PASSWORD,
        )
    uvicorn.run(
        "server.app:create_production_app",
        factory=True,
        reload=False,
        port=prod_settings.PORT,
        log_level=prod_settings.LOG_LEVEL,
        workers=prod_settings.WORKERS,
        host="0.0.0.0",
        forwarded_allow_ips=prod_settings.PROXY_IP,
        proxy_headers=True,
        **args,
    )


if __name__ == "__main__":
    main()
