FROM python:3.11.16-slim-trixie@sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY requirements-build.lock pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock

COPY unrender ./unrender
RUN python -m build --wheel --no-isolation --outdir /dist

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
    && chown unrender:unrender /data \
    && chmod 0700 /data

COPY requirements-app.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-app.lock

COPY --from=builder /dist/unrender-*.whl /tmp/unrender-wheel/
RUN set -eu; \
    set -- /tmp/unrender-wheel/unrender-*.whl; \
    [ "$#" -eq 1 ]; \
    [ -f "$1" ]; \
    python -m pip install --no-cache-dir --no-deps "$1"; \
    rm -r /tmp/unrender-wheel

USER unrender
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
  CMD ["unrender-healthcheck"]

CMD ["unrender-serve"]
