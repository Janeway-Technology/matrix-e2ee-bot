"""Input validation helpers."""

import re

_ROOM_ID_RE = re.compile(r"^![^:]+:.+$")
_USER_ID_RE = re.compile(r"^@[^:]+:.+$")


def is_valid_room_id(room_id: str) -> bool:
    return bool(_ROOM_ID_RE.match(room_id))


def is_valid_user_id(user_id: str) -> bool:
    return bool(_USER_ID_RE.match(user_id))
