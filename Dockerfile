# Poetry only exports the locked requirements here. Installing it alongside the
# app let its own unpinned dependencies (e.g. charset-normalizer) collide with
# the locked versions and leave a broken mix of files behind.
FROM python:3.12-slim AS requirements

ENV POETRY_VERSION=1.8.3

WORKDIR /tmp

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock ./
RUN poetry export --only main --without-hashes -f requirements.txt -o requirements.txt


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=requirements /tmp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
