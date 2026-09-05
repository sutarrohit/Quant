"""Domain errors raised by the service layer.

Services never import FastAPI. They raise these instead, and `main.py` maps them
onto HTTP responses. That keeps the services reusable from scripts, workers and
tests without an HTTP request in play.
"""

from fastapi import status


class ServiceError(Exception):
    """Base class for expected, recoverable domain failures."""

    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(ServiceError):
    """A uniqueness constraint would be violated (duplicate username or email)."""

    status_code = status.HTTP_400_BAD_REQUEST


class PermissionDeniedError(ServiceError):
    status_code = status.HTTP_403_FORBIDDEN


class AuthenticationError(ServiceError):
    status_code = status.HTTP_401_UNAUTHORIZED


class UnsupportedMediaError(ServiceError):
    status_code = status.HTTP_400_BAD_REQUEST


class PayloadTooLargeError(ServiceError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
