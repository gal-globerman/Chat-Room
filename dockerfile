FROM python:3.11-slim-bookworm as builder

RUN pip install poetry==1.7.1

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

COPY pyproject.toml poetry.lock ./

RUN poetry install --no-dev --no-root && rm -rf $POETRY_CACHE_DIR


FROM python:3.11-slim-bookworm as runtime

COPY --from=builder .venv .venv

COPY app ./app

CMD [".venv/bin/uvicorn", "app.main:app", "--timeout-graceful-shutdown", "1"]
