"""Pydantic request/response models."""

from typing import Optional
from pydantic import BaseModel, field_validator
from app.utils.validators import is_valid_room_id, is_valid_user_id


class SendRequest(BaseModel):
    room_id: str
    message: str
    msgtype: str = "m.text"

    @field_validator("room_id")
    @classmethod
    def validate_room_id(cls, v: str) -> str:
        if not is_valid_room_id(v):
            raise ValueError("Invalid room_id format, expected !localpart:server")
        return v

    @field_validator("msgtype")
    @classmethod
    def validate_msgtype(cls, v: str) -> str:
        allowed = {"m.text", "m.notice", "m.emote"}
        if v not in allowed:
            raise ValueError(f"msgtype must be one of {allowed}")
        return v


class JoinRequest(BaseModel):
    room_id: str

    @field_validator("room_id")
    @classmethod
    def validate_room_id(cls, v: str) -> str:
        if not is_valid_room_id(v):
            raise ValueError("Invalid room_id format")
        return v


class CreateRoomRequest(BaseModel):
    name: str
    topic: Optional[str] = None
    invite: Optional[list[str]] = None
    encrypted: bool = True

    @field_validator("invite", mode="before")
    @classmethod
    def validate_invites(cls, v: Optional[list]) -> Optional[list]:
        if v is None:
            return v
        for uid in v:
            if not is_valid_user_id(uid):
                raise ValueError(f"Invalid user_id in invite list: {uid}")
        return v


class VerifyDeviceRequest(BaseModel):
    user_id: str
    device_id: str

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        if not is_valid_user_id(v):
            raise ValueError("Invalid user_id format, expected @user:server")
        return v


class InviteRequest(BaseModel):
    room_id: str
    user_id: str

    @field_validator("room_id")
    @classmethod
    def validate_room_id(cls, v: str) -> str:
        if not is_valid_room_id(v):
            raise ValueError("Invalid room_id format")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        if not is_valid_user_id(v):
            raise ValueError("Invalid user_id format, expected @user:server")
        return v
