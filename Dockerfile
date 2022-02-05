FROM python:3.9.10-alpine AS prod
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
RUN pipenv install --system --deploy
EXPOSE 5789
ENTRYPOINT [ "python3", "main_prod.py" ]
