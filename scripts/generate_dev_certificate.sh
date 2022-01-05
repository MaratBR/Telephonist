#!/bin/bash

_ROOT=$(dirname "$(dirname "$0")")
cd "$_ROOT/certs" || exit
openssl req -x509 -new -nodes -days 720 -keyout key.pem -out cert.crt -config dev_certificate.conf
echo "Copying dev certificate to /usr/local/share/ca-certificates/telephonist_dev_certificate.crt"
sudo cp cert.crt /usr/local/share/ca-certificates/telephonist_dev_certificate.crt
sudo update-ca-certificates
