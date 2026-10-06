from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging

from src.core.config import settings
from src.core.errors import AppError
from src.core.request_id import (
    REQUEST_ID_HEADER,
    RequestIdLogFilter,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)
from src.routes import stocks, users, watchlist, auth, simulator, strategies, market_data, dev

app = FastAPI()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:[%(request_id)s] %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdLogFilter())
logger = logging.getLogger("investoryx")


def internal_error_response(request_id: str, exc: Exception) -> JSONResponse:
    content = {"detail": "Internal Server Error", "request_id": request_id}
    if settings.debug_errors:
        content.update(detail=str(exc), error_type=exc.__class__.__name__)
    return JSONResponse(
        status_code=500, content=content, headers={REQUEST_ID_HEADER: request_id}
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    token = set_request_id(request_id)
    try:
        logger.info("Request start %s %s", request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception as exc:
            # Answer here rather than in an app-level Exception handler: that one
            # runs outside the CORS middleware, so browsers couldn't read the 500.
            logger.exception("Unhandled error %s %s", request.method, request.url.path)
            response = internal_error_response(request_id, exc)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info("Request end %s %s -> %s", request.method, request.url.path, response.status_code)
        return response
    finally:
        reset_request_id(token)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Fallback for errors raised outside log_requests (e.g. in other middleware).
    logger.exception("Unhandled exception during request: %s %s", request.method, request.url.path)
    request_id = getattr(request.state, "request_id", None) or resolve_request_id(None)
    return internal_error_response(request_id, exc)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets the frontend read the ID to report alongside errors.
    expose_headers=[REQUEST_ID_HEADER],
)

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

# DATABASE ROUTES --------------------------------------------------------------------------------------
app.include_router(stocks.router)
app.include_router(users.router)
app.include_router(watchlist.router)
app.include_router(auth.router)
app.include_router(simulator.router)
app.include_router(strategies.router)
app.include_router(market_data.router)
app.include_router(dev.router)


