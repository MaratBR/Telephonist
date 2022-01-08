import os.path

import uvicorn

if __name__ == "__main__":
    args = {}
    if os.path.isfile("certs/cert.crt") and os.path.isfile("certs/key.pem"):
        args.update(
            ssl_keyfile="certs/key.pem", ssl_certfile="certs/cert.crt", ssl_keyfile_password="1234"
        )
    uvicorn.run("server.app:create_app", factory=True, reload=True, port=5789, **args)
