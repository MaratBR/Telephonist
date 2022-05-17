FROM maratbr/telephonist-admin:latest AS frontend
FROM maratbr/telephonist:latest AS backend

ENV DOCKERIZE_VERSION v0.6.1
RUN wget https://github.com/jwilder/dockerize/releases/download/$DOCKERIZE_VERSION/dockerize-alpine-linux-amd64-$DOCKERIZE_VERSION.tar.gz \
    && tar -C /bin -xzvf dockerize-alpine-linux-amd64-$DOCKERIZE_VERSION.tar.gz \
    && rm dockerize-alpine-linux-amd64-$DOCKERIZE_VERSION.tar.gz
COPY --from=frontend /dist /spa
RUN cp /spa/index.html index.html.tmpl
ENV API_URL=/
RUN /bin/dockerize -template index.html.tmpl:/spa/index.html


ENV TELEPHONIST_SPA_PATH=/spa
ENV TELEPHONIST_DISABLE_SSL=True
ENV TELEPHONIST_COOKIES_POLICY=Lax