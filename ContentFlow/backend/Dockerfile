# Content Flow API image (used by Koyeb; works on any Docker host).
# Python 3.9 matches the version the test suite runs on.
FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Koyeb free has no persistent disk: the database is Neon (CONTENT_FLOW_DATABASE_URL)
    # and media is Cloudinary (CLOUDINARY_URL); this folder only holds a download cache.
    CONTENT_FLOW_DATA_DIR=/tmp/contentflow \
    PORT=8000

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 contentflow
USER contentflow

EXPOSE 8000
# One worker only: the publisher runs inside the API process and must not run twice.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
