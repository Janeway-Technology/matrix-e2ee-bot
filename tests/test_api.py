"""Basic API tests using httpx AsyncClient (no real Matrix server needed)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


@pytest.fixture(autouse=True)
def stub_matrix_client(monkeypatch):
    """Replace the real MatrixClientManager with a stub."""

    class StubClient:
        def health(self):
            return {
                "status": "ok",
                "user_id": "@bot:example.com",
                "device_id": "TESTDEVICE",
                "logged_in": True,
                "e2ee_enabled": True,
                "sync_running": True,
            }

        async def send_message(self, room_id, message, msgtype="m.text"):
            return {"status": "sent", "event_id": "$test_event", "encrypted": True}

        async def join_room(self, room_id):
            return {"status": "joined", "room_id": room_id}

        async def create_room(self, name, topic=None, invite=None, encrypted=True):
            return {"status": "created", "room_id": "!new:example.com"}

        async def invite_user(self, room_id, user_id):
            return {"status": "invited", "room_id": room_id, "user_id": user_id}

        async def get_rooms(self):
            return {"rooms": [{"room_id": "!test:example.com", "name": "Test", "encrypted": True, "member_count": 2}]}

    app.state.matrix_client = StubClient()


AUTH = {"Authorization": f"Bearer {settings.api_bearer_token}"}
ROOM = "!testroom:example.com"
USER = "@alice:example.com"


def test_health_no_auth():
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_send_message():
    with TestClient(app) as c:
        r = c.post("/send", json={"room_id": ROOM, "message": "Hello"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "sent"


def test_send_requires_auth():
    with TestClient(app) as c:
        r = c.post("/send", json={"room_id": ROOM, "message": "Hello"})
    assert r.status_code == 403


def test_send_invalid_room():
    with TestClient(app) as c:
        r = c.post("/send", json={"room_id": "not_a_room", "message": "Hi"}, headers=AUTH)
    assert r.status_code == 422


def test_join_room():
    with TestClient(app) as c:
        r = c.post("/join", json={"room_id": ROOM}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "joined"


def test_create_room():
    with TestClient(app) as c:
        r = c.post("/create-room", json={"name": "My Room"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "created"


def test_invite_user():
    with TestClient(app) as c:
        r = c.post("/invite", json={"room_id": ROOM, "user_id": USER}, headers=AUTH)
    assert r.status_code == 200


def test_get_rooms():
    with TestClient(app) as c:
        r = c.get("/rooms", headers=AUTH)
    assert r.status_code == 200
    assert "rooms" in r.json()


def test_bad_bearer_token():
    with TestClient(app) as c:
        r = c.get("/rooms", headers={"Authorization": "Bearer wrong_token"})
    assert r.status_code == 401
