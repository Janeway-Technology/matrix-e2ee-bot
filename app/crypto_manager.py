"""E2EE crypto store management for matrix-nio."""

import os
from pathlib import Path
from typing import Optional

from nio import AsyncClient, ClientConfig
from nio.store import SqliteStore

from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_client_config() -> ClientConfig:
    """Return a ClientConfig with E2EE enabled."""
    return ClientConfig(
        store_sync_tokens=True,
        encryption_enabled=True,
    )


def get_store_path(crypto_store_path: str, user_id: str) -> tuple[str, str]:
    """Return (store_dir, store_filename) for a given user."""
    store_dir = Path(crypto_store_path)
    store_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize user_id for use as filename
    safe_user = user_id.replace("@", "").replace(":", "_").replace(".", "_")
    return str(store_dir), f"{safe_user}.db"


def create_client(
    homeserver: str,
    user_id: str,
    device_id: Optional[str],
    crypto_store_path: str,
) -> AsyncClient:
    """Instantiate an AsyncClient with E2EE crypto store configured."""
    store_dir, store_file = get_store_path(crypto_store_path, user_id)
    config = build_client_config()

    client = AsyncClient(
        homeserver=homeserver,
        user=user_id,
        device_id=device_id or "",
        store_path=store_dir,
        config=config,
    )
    logger.info(
        "matrix_client_created",
        homeserver=homeserver,
        user_id=user_id,
        store_dir=store_dir,
    )
    return client
