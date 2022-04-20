## Some scripts

```shell
sudo docker run -p 27017:27017 mongo
sudo docker run -p 6379:6379 redis
```

```shell
sudo docker volume rm mongodb_volume
sudo docker volume create mongodb_volume

sudo docker container rm mongodb_database -f
sudo docker run\
  -d\
  --name mongodb_database\
  -p 4999:27017\
  --restart always\
  --mount source=mongodb_volume,target=/data\
  mongo

sudo docker container rm redis_service -f

sudo docker run \
  -d \
  --name redis_service \
  -p 6379:6379 \
  --restart always \
  redis \
  --requirepass ugabuga
```

```shell
helm upgrade --install ingress-nginx ingress-nginx   --repo https://kubernetes.github.io/ingress-nginx   --namespace ingress-nginx --create-namespace
```

```shell
docker run \
  -e TELEPHONIST_CORS_ORIGINS=[\"http://admin.telephonist.lc:8000\"] \
  -e TELEPHONIST_SECRET=secret \
  -e TELEPHONIST_SSL_CERT=/certs/cert.crt \
  -e TELEPHONIST_SSL_KEY=/certs/key.pem \
  -e TELEPHONIST_DB_URL=mongodb://127.0.0.1:27017 \
  -e TELEPHONIST_REDIS_URL=redis://127.0.0.1:6379 \
  --mount type=bind,source=$(pwd)/certs,target=/certs \
  --net=host \
  maratbr/telephonist:latest
  
docker run \
  -e TELEPHONIST_CORS_ORIGINS=[\"http://admin.telephonist.lc:8000\"] \
  -e TELEPHONIST_SECRET=secret \
  -e TELEPHONIST_DISABLE_SSL=True \
  -e TELEPHONIST_SSL_KEY=/certs/key.pem \
  -e TELEPHONIST_DB_URL=mongodb://127.0.0.1:27017 \
  -e TELEPHONIST_REDIS_URL=redis://127.0.0.1:6379 \
  --mount type=bind,source=$(pwd)/certs,target=/certs \
  --net=host \
  maratbr/telephonist:latest
  
docker run \
  -e API_URL=https://api.telephonist.lc:5789 \
  -e NGINX_SERVER_NAME=admin.telephonist.lc \
  -p 8000:80 \
  maratbr/telephonist-admin:latest 
```