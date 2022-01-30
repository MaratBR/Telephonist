import logging
import os.path

import uvicorn

if __name__ == "__main__":
    args = {}
    is_ssl_disabled = os.environ.get("DISABLE_SSL_IN_DEBUG") is not None
    if os.path.isfile("certs/cert.crt") and os.path.isfile("certs/key.pem") and not is_ssl_disabled:
        args.update(
            ssl_keyfile="certs/key.pem", ssl_certfile="certs/cert.crt", ssl_keyfile_password="1234"
        )
    if is_ssl_disabled:
        print("DISABLE_SSL_IN_DEBUG is set, SSL is disabled, serving from HTTP")
    uvicorn.run("server.app:create_app", factory=True, reload=True, port=5789, **args)
