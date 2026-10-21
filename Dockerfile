FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# Dev image: includes pytest/ruff so the test suite can run inside the container.
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY alembic.ini pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY tests ./tests

RUN useradd --create-home --uid 10001 infrascope
USER infrascope

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# Apply migrations, then serve. One worker: the monitor runs in-process (see ARCHITECTURE.md).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1"]
