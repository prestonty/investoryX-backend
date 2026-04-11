# InvestoryX Backend

## Architecture
FastAPI app with SQLAlchemy ORM, Celery for async tasks, and PostgreSQL. Routes live in `src/routes/`, business logic in `src/services/`, DB models in `src/models/`, and Pydantic schemas in `src/schemas/`.

## Naming Conventions
- Files & folders: `snake_case`
- Classes: `PascalCase` (models, schemas, routers)
- Functions & variables: `snake_case`
- DB columns: `snake_case`; JSON responses may use `camelCase` via Pydantic `alias`
- Router prefixes: `/api/<resource>` (plural noun)

## Build & Run
```bash
# Install deps
poetry install

# Run dev server
uvicorn src.main:app --reload

# Run migrations
alembic upgrade head

# Run Celery worker
celery -A src.celery_app worker --loglevel=info

# Run tests
pytest
```
