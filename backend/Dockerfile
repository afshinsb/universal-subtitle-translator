FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS dependencies

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
# pysrt is distributed as an sdist; build it using explicit tooling versions.
RUN pip install --no-cache-dir pip==26.2.1 setuptools==84.0.0 wheel==0.48.0 packaging==26.3 \
    && pip install --no-cache-dir --no-build-isolation --require-hashes -r requirements.txt \
    && pip uninstall -y setuptools wheel packaging

FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ARG APP_VERSION=1.8.2
LABEL org.opencontainers.image.title="Universal Subtitle Translator backend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/afshinsb/universal-subtitle-translator"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    DEV_MODE=false \
    DATA_DIR=/app/data \
    UPLOAD_DIR=/app/data/uploads \
    OUTPUT_DIR=/app/data/outputs \
    TEMP_DIR=/app/data/temp \
    DATABASE_PATH=/app/data/app.db
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --no-create-home app \
    && mkdir -p /app/data \
    && chown app:app /app/data
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=app:app app ./app
USER 1000:1000
EXPOSE 2288
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('APP_PORT','2288')+'/health',timeout=3).read()"
CMD ["python", "-m", "app"]
