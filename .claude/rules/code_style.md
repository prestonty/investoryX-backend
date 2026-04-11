# Code Style & Standards

## Formatter & Linter
- **Black** for formatting (`line-length = 88`)
- **Flake8** for linting (`max-line-length = 88`, ignores `E203`, `W503`)
- Run before committing: `black src/ && flake8 src/`

## Python Standards
- Python 3.12+; use built-in type hints (`list[str]` not `List[str]`)
- Prefer `|` union syntax over `Optional[X]` (e.g., `str | None`)
- Use `pydantic` `BaseModel` for all request/response shapes — never raw dicts at route boundaries
- Avoid mutable default arguments; use `field(default_factory=...)` in dataclasses/Pydantic

## FastAPI Patterns
- One router per resource file in `src/routes/`; register in `src/main.py`
- Always declare `response_model` on route decorators
- Use `Depends()` for DB sessions and auth — never instantiate directly in handlers
- Raise `HTTPException` for expected errors; let the global handler catch unexpected ones
- Keep route handlers thin: delegate logic to `src/services/`

## SQLAlchemy
- Define models in `src/models/`; one model per file when practical
- Always use typed columns (`Mapped[int]`, `mapped_column(...)`) with SQLAlchemy 2.x style
- Never commit inside a service — let the caller (route handler) manage the session lifecycle

## General
- No bare `except:` — always catch a specific exception or `Exception` with logging
- Log with the named logger (`logging.getLogger("investoryx")`), not `print()`
- Keep functions under ~40 lines; extract helpers rather than nesting deeply
