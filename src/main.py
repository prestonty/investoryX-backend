import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import logging
from alembic.config import Config
from alembic import command

from src.api.routes import stocks, users, watchlist, auth, simulator, market_data, email

# Load environment variables
load_dotenv()

origins = [
    "https://investory-six.vercel.app",
    os.getenv("FRONTEND_BASE_URL"),
    "https://www.investoryx.ca",
]

app = FastAPI()
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "false").lower() in ("1", "true", "yes")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("investoryx")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("Request start %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error %s %s", request.method, request.url.path)
        raise
    logger.info("Request end %s %s -> %s", request.method, request.url.path, response.status_code)
    return response

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception during request: %s %s", request.method, request.url.path)
    if DEBUG_ERRORS:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "error_type": exc.__class__.__name__},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}

# DATABASE ROUTES --------------------------------------------------------------------------------------
app.include_router(stocks.router)
app.include_router(users.router)
app.include_router(watchlist.router)
app.include_router(auth.router)
app.include_router(simulator.router)
app.include_router(market_data.router)
app.include_router(email.router)

# DB Start up after deploying
@app.on_event("startup")
async def run_migrations():
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")



