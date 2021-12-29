import uvicorn

if __name__ == "__main__":
    uvicorn.run("server.app:app", reload=False, port=5789)
    # uvicorn.run('server:app', reload=True, uds='/tmp/telephonist.sock', forwarded_allow_ips='*')
