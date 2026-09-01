# syntax=docker/dockerfile:1.7
FROM python:3.11.16-slim-trixie@sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UNRENDER_DATA_DIR=/data \
    UNRENDER_HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

RUN groupadd --gid 10001 unrender \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin unrender \
    && mkdir -p /data \
    && chown unrender:unrender /data

COPY requirements-app.lock pyproject.toml README.md LICENSE ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-app.lock

COPY unrender ./unrender
RUN python -m pip install --no-cache-dir --no-deps .

USER unrender
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)" || exit 1

CMD ["unrender-serve"]
