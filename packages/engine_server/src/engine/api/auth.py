"""Authentication (spec section 7.2).

A single static bearer token shared with ``api-control``, which is the only
caller. Nothing more elaborate is in scope (spec section 1) -- this service is
not internet-facing and has one client.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from engine.api.deps import SettingsDep
from engine.errors import UnauthenticatedError

# auto_error=False so a missing header produces our error envelope rather than
# FastAPI's, and the caller sees one shape for every failure.
_scheme = HTTPBearer(auto_error=False)


async def require_internal_token(
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_scheme)],
) -> None:
    expected = settings.require_internal_api_key().get_secret_value()
    presented = credentials.credentials if credentials else ""
    # Constant time: a plain == leaks the token one character at a time.
    if not secrets.compare_digest(presented, expected):
        raise UnauthenticatedError("a valid internal bearer token is required")


InternalAuth = Depends(require_internal_token)
