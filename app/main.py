"""FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.routes import router
from app.config import settings
from app.matrix_client import MatrixClientManager
from app.utils.logger import get_logger, setup_logging

setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Matrix client lifecycle alongside the FastAPI app."""
    mgr = MatrixClientManager(settings)
    app.state.matrix_client = mgr

    try:
        logger.info("starting_matrix_client")
        await mgr.start()
        logger.info("matrix_client_ready")
    except Exception as exc:
        logger.error("matrix_client_start_failed", error=str(exc))
        # Still expose /health so the container health check can report the error
        app.state.matrix_client = _FailedClientStub(str(exc))

    yield

    logger.info("shutting_down_matrix_client")
    await mgr.stop()


class _FailedClientStub:
    """Minimal stub returned when the real client fails to start."""
    def __init__(self, error: str) -> None:
        self._error = error

    def health(self) -> dict:
        return {
            "status": "error",
            "error": self._error,
            "logged_in": False,
            "e2ee_enabled": False,
        }


app = FastAPI(
    title="Matrix E2EE Bot Service",
    description="Production-ready Matrix bot with End-to-End Encryption via REST API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "Validation error", "code": "VALIDATION_ERROR", "details": exc.errors()},
    )
