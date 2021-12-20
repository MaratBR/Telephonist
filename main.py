import uvicorn

if __name__ == '__main__':
    uvicorn.run('server:app', reload=True, uds='/tmp/telephonist.sock', forwarded_allow_ips='*')
