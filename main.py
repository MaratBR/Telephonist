import argparse
import logging
import os.path
import sys

import anyio
import uvicorn

if __name__ == "__main__":
    args = {}
    is_ssl_disabled = os.environ.get("DISABLE_SSL_IN_DEBUG") is not None
    if (
        os.path.isfile("certs/cert.crt")
        and os.path.isfile("certs/key.pem")
        and not is_ssl_disabled
    ):
        args.update(
            ssl_keyfile="certs/key.pem",
            ssl_certfile="certs/cert.crt",
            ssl_keyfile_password="1234",
        )
    if is_ssl_disabled:
        print(
            "DISABLE_SSL_IN_DEBUG is set, SSL is disabled, serving from HTTP"
        )
    parser = argparse.ArgumentParser(description="Process some integers.")
    parser.add_argument("--reload", action="store_const", const=True)
    sys_args = parser.parse_args(sys.argv[1:])

    uvicorn.run(
        "server.app_debug:create_debug_app",
        factory=True,
        reload=sys_args.reload or False,
        port=5789,
        **args
    )
