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

helm upgrade --install ingress-nginx ingress-nginx   --repo https://kubernetes.github.io/ingress-nginx   --namespace ingress-nginx --create-namespace