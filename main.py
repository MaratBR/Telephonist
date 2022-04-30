from typing import Optional

import uvicorn
from pydantic import BaseSettings, Field


class EnvSettings(BaseSettings):
    disable_ssl: bool = False
    ssl_cert: Optional[str]
    ssl_key: Optional[str]
    ssl_password: Optional[str]
    workers: int = 1
    log_level: str = Field(default="info")
    port: int = Field(default=5789, ge=1024, lt=32768)
    proxy_ip: Optional[str] = None
    proxy_headers: bool = True

    class Config:
        env_prefix = "TELEPHONIST_"


def main():
    prod_settings = EnvSettings()
    args = {}
    print(f"Running on port {prod_settings.port}")
    if not prod_settings.disable_ssl:
        assert prod_settings.ssl_key and prod_settings.ssl_cert, (
            "You must either provide ssl key path and ssl certificate through"
            " TELEPHONIST_SSL_KEY and TELEPHONIST_SSL_CERT env. variables or"
            " set TELEPHONIST_DISABLE_SSL to True"
        )
        args.update(
            ssl_keyfile=prod_settings.ssl_key,
            ssl_certfile=prod_settings.ssl_cert,
            ssl_keyfile_password=prod_settings.ssl_password,
        )
    uvicorn.run(
        "server.app:create_production_app",
        factory=True,
        reload=False,
        port=prod_settings.port,
        log_level=prod_settings.log_level,
        workers=prod_settings.workers,
        host="0.0.0.0",
        forwarded_allow_ips=prod_settings.proxy_ip,
        proxy_headers=prod_settings.proxy_headers,
        **args,
    )


if __name__ == "__main__":
    main()
