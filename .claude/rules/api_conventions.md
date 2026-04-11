# API Conventions

## URL Structure
- Base prefix: `/api/<resource>` (lowercase plural noun)
- Resource by ID: `/api/<resource>/{id}`
- Nested resource: `/api/<resource>/{id}/<sub-resource>`
- Actions that aren't CRUD: `/api/<resource>/{id}/<verb>` (e.g., `/api/simulator/{id}/reset`)

## HTTP Methods
| Intent         | Method   |
|----------------|----------|
| Read list      | `GET`    |
| Read one       | `GET`    |
| Create         | `POST`   |
| Full replace   | `PUT`    |
| Partial update | `PATCH`  |
| Delete         | `DELETE` |

## Request & Response Shape
- Request bodies: Pydantic `BaseModel` with `snake_case` fields
- Response bodies: Pydantic `BaseModel`; use `alias` + `populate_by_name=True` when camelCase is needed by the frontend
- Always wrap errors as `{"detail": "<message>"}` (FastAPI default)
- Paginated lists should return `{"items": [...], "total": N}`

## Status Codes
- `200` — successful read or update
- `201` — resource created
- `204` — successful delete (no body)
- `400` — bad request / validation failure
- `401` — unauthenticated
- `403` — authenticated but forbidden
- `404` — resource not found
- `500` — unhandled server error (global handler)

## Authentication
- JWT bearer token via `Authorization: Bearer <token>`
- Protected routes use `Depends(get_current_active_user)`
- Auth routes live under `/api/auth/`

## Versioning
- No versioning prefix currently; introduce `/api/v2/` only when breaking changes are required
