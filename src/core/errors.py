"""Errors with a stable machine-readable code.

Raise AppError instead of HTTPException when a client needs to tell this error
apart from others (e.g. show a specific message or take an action). The JSON
body keeps FastAPI's `detail` and adds `code`; codes are part of the API
contract, so change a code only together with the frontend.
"""

from fastapi import HTTPException


class ErrorCode:
    INVALID_CREDENTIALS = "invalid_credentials"
    EMAIL_NOT_VERIFIED = "email_not_verified"
    EMAIL_TAKEN = "email_taken"


class AppError(HTTPException):
    """An HTTPException that also carries a `code`.

    Subclassing HTTPException keeps existing `except HTTPException: raise`
    blocks working.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
