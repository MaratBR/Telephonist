FROM python:3.9.10-alpine

# install rust and cargo, they're required for cryptography
RUN apk add \
    gcc \
    libc-dev \
    make \
    git \
    libffi-dev \
    openssl-dev \
    python3-dev \
    libxml2-dev \
    libxslt-dev \
    rust \
    cargo

RUN pip3 install pipenv
WORKDIR /app
COPY . /app
ENV PIPENV_NOSPIN=1
ENV PIPENV_HIDE_EMOJIS=1
ENV TELEPHONIST_EXECUTION_ENVIRONMENT_TYPE=docker
ENV TELEPHONIST_PORT=5789
RUN pipenv install --system --deploy
EXPOSE 5789
ENTRYPOINT [ "python3", "main.py" ]
