"""API route definitions."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.auth import require_auth
from app.api.models import (
    CreateRoomRequest,
    InviteRequest,
    JoinRequest,
    SendRequest,
    VerifyDeviceRequest,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _client(request: Request):
    """Extract MatrixClientManager from app state."""
    return request.app.state.matrix_client


# ---------------------------------------------------------------------------
# Health (no auth)
# ---------------------------------------------------------------------------

@router.get("/health")
async def health(request: Request):
    """Return bot health/status. No authentication required."""
    mgr = _client(request)
    return mgr.health()


# ---------------------------------------------------------------------------
# Protected endpoints
# ---------------------------------------------------------------------------

@router.post("/send", dependencies=[Depends(require_auth)])
async def send_message(body: SendRequest, request: Request):
    try:
        return await _client(request).send_message(
            room_id=body.room_id,
            message=body.message,
            msgtype=body.msgtype,
        )
    except RuntimeError as exc:
        logger.error("send_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": str(exc), "code": "SEND_FAILED"},
        )


@router.post("/join", dependencies=[Depends(require_auth)])
async def join_room(body: JoinRequest, request: Request):
    try:
        return await _client(request).join_room(room_id=body.room_id)
    except RuntimeError as exc:
        logger.error("join_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": str(exc), "code": "JOIN_FAILED"},
        )


@router.post("/create-room", dependencies=[Depends(require_auth)])
async def create_room(body: CreateRoomRequest, request: Request):
    try:
        return await _client(request).create_room(
            name=body.name,
            topic=body.topic,
            invite=body.invite,
            encrypted=body.encrypted,
        )
    except RuntimeError as exc:
        logger.error("create_room_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": str(exc), "code": "CREATE_ROOM_FAILED"},
        )


@router.post("/invite", dependencies=[Depends(require_auth)])
async def invite_user(body: InviteRequest, request: Request):
    try:
        return await _client(request).invite_user(
            room_id=body.room_id,
            user_id=body.user_id,
        )
    except RuntimeError as exc:
        logger.error("invite_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": str(exc), "code": "INVITE_FAILED"},
        )


@router.get("/devices/{user_id}", dependencies=[Depends(require_auth)])
async def list_devices(user_id: str, request: Request):
    """List all known devices for a user (needed to find device_id before verifying)."""
    try:
        return await _client(request).list_user_devices(user_id=user_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": str(exc), "code": "LIST_DEVICES_FAILED"},
        )


@router.post("/verify-device", dependencies=[Depends(require_auth)])
async def verify_device(body: VerifyDeviceRequest, request: Request):
    """Start bot-initiated SAS verification with a specific device.

    The user must accept the verification request in Element,
    then compare emojis shown in 'docker logs matrix-e2ee-bot' with Element.
    """
    try:
        return await _client(request).start_verification(
            user_id=body.user_id,
            device_id=body.device_id,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc), "code": "VERIFY_FAILED"},
        )


@router.get("/rooms", dependencies=[Depends(require_auth)])
async def get_rooms(request: Request):
    try:
        return await _client(request).get_rooms()
    except RuntimeError as exc:
        logger.error("get_rooms_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": str(exc), "code": "GET_ROOMS_FAILED"},
        )
