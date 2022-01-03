import os.path

import uvicorn

if __name__ == "__main__":
    args = {}
    if os.path.isfile("certs/cert.pem") and os.path.isfile("certs/key.pem"):
        args.update(
            ssl_keyfile="certs/key.pem", ssl_certfile="certs/cert.pem", ssl_keyfile_password="1234"
        )
    uvicorn.run("server.app:app", reload=False, port=5789, **args)
    # uvicorn.run('server:app', reload=True, uds='/tmp/telephonist.sock', forwarded_allow_ips='*')
