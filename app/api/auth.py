"""Bearer token authentication dependency."""

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer_scheme = HTTPBearer(auto_error=True)


def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> None:
    """FastAPI dependency that validates the Bearer token."""
    if credentials.credentials != settings.api_bearer_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid or missing bearer token", "code": "UNAUTHORIZED"},
            headers={"WWW-Authenticate": "Bearer"},
        )
