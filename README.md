## Some scripts

```shell
sudo docker run -p 27017:27017 mongo
sudo docker run -p 6379:6379 redis
```

Running database:
```shell
sudo docker volume create mongodb_volume
sudo docker run\
  -d\
  --name mongodb_database\
  -p 27017:27017\
  --restart always\
  --mount source=mongodb_volume,target=/data\
  -e MONGO_INITDB_ROOT_USERNAME="MONGODB_USERNAME"\
  -e MONGO_INITDB_ROOT_PASSWORD="MONGODB_PASSWORD"\
  mongo
```

Running redis:
```shell
sudo docker run \
  -d \
  --name redis_service \
  -p 6379:6379 \
  --restart always \
  redis redis-server --appendonly yes  --requirepass "REDIS_PASSWORD" 
```

Helm:
```shell
helm upgrade --install ingress-nginx ingress-nginx   --repo https://kubernetes.github.io/ingress-nginx   --namespace ingress-nginx --create-namespace
```

Server/client:
```shell
sudo docker run\
  -d\
  -e TELEPHONIST_REDIS_URL="redis://localhost:6379/?password=REDIS_PASSWORD"\
  -e TELEPHONIST_DB_URL="mongodb://MONGODB_USERNAME:MONGODB_PASSWORD@localhost:27017"\
  --name telephonist_all_in_one\
  --restart always\
  -e TELEPHONIST_SECRET="SECRET_KEY"\
  maratbr/telephonist-all-in-one
```

```shell
# With SSL
docker run \
  -e TELEPHONIST_SECRET=secret \
  -e TELEPHONIST_SSL_CERT=/certs/cert.crt \
  -e TELEPHONIST_SSL_KEY=/certs/key.pem \
  -e TELEPHONIST_DB_URL=mongodb://127.0.0.1:27017 \
  -e TELEPHONIST_REDIS_URL=redis://127.0.0.1:6379 \
  --mount type=bind,source=$(pwd)/certs,target=/certs \
  --net=host \
  maratbr/telephonist:latest
  
# Without SSL AND behind proxy
sudo docker run \
  -e TELEPHONIST_SECRET=secret \
  -e TELEPHONIST_DISABLE_SSL=True \
  -e TELEPHONIST_DB_URL=mongodb://127.0.0.1:27017 \
  -e TELEPHONIST_REDIS_URL=redis://127.0.0.1:6379 \
  -e TELEPHONIST_COOKIES_POLICY=Lax \
  -e TELEPHONIST_USE_NON_SECURE_COOKIES=True \
  -e TELEPHONIST_PORT=30890 \
  -e TELEPHONIST_PROXY_HEADERS=True \
  --name telephonist \
  -d \
  --net=host \
  maratbr/telephonist:latest
  
docker run \
  -e API_URL=/ \
  -p 8080:80 \
  --name telephonist-admin \
  maratbr/telephonist-admin:latest 
```