"""Per-request IDs, so one failed request can be traced from the browser to the logs.

The frontend sends an X-Request-ID header; requests without one get a fresh ID.
The ID is echoed back on the response and added to every log line written while
the request is handled.
"""

import logging
import re
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Accept only short, plain IDs from clients so they can't inject log lines.
_VALID_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def resolve_request_id(incoming: str | None) -> str:
    if incoming and _VALID_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


def set_request_id(request_id: str):
    """Sets the ID for the current request; returns a token for reset_request_id."""
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def get_request_id() -> str:
    return _request_id.get()


class RequestIdLogFilter(logging.Filter):
    """Adds `request_id` to log records ("-" outside a request)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
