import argparse
import os.path
import sys

import uvicorn


def main(reload=False):
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

    uvicorn.run(
        "server.app_debug:create_debug_app",
        factory=True,
        reload=reload,
        port=5789,
        proxy_headers=True,
        forwarded_allow_ips="*",
        **args
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process some integers.")
    parser.add_argument("--reload", action="store_const", const=True)
    sys_args = parser.parse_args(sys.argv[1:])

    main(reload=sys_args.reload)
