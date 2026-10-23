FROM python:3.12.8-alpine@sha256:ba13ef990f6e5d13014e9e8d04c02a8fdb0fe53d6dccf6e19147f316e6cc3a84

ARG TARGETARCH
RUN apk add --no-cache \
      bash=5.2.37-r0 \
      coreutils=9.5-r2
COPY wheels/${TARGETARCH}/ /opt/wheels/
ENV UV_FIND_LINKS=/opt/wheels
RUN adduser -D -u 10001 worker
WORKDIR /workspace
COPY workspace/ /workspace/
RUN chown -R worker:worker /workspace
USER worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

CMD ["bash"]
