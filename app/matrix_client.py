"""Matrix client wrapper with E2EE support and background sync."""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from nio import (
    AsyncClient,
    LoginResponse,
    LoginError,
    RoomSendResponse,
    RoomSendError,
    JoinResponse,
    JoinError,
    RoomCreateResponse,
    RoomCreateError,
    RoomInviteResponse,
    RoomInviteError,
    KeysUploadResponse,
    SyncError,
    RoomEncryptionEvent,
    MegolmEvent,
    LocalProtocolError,
    ToDeviceMessage,
    ToDeviceError,
    UnknownToDeviceEvent,
    KeyVerificationCancel,
    KeyVerificationKey,
    KeyVerificationMac,
)
from nio.crypto import Sas
from nio.exceptions import OlmUnverifiedDeviceError

from app.config import Settings
from app.crypto_manager import create_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

SESSION_FILE = Path("/app/data/session.json")


class MatrixClientManager:
    """Manages the Matrix AsyncClient lifecycle, login, sync, and messaging."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Optional[AsyncClient] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()
        self._logged_in = False
        self._e2ee_enabled = False
        # txn_id -> (user_id, device_id, OlmDevice) for pending verification requests
        self._pending_verifications: dict = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Login, upload keys, run initial sync, then start background sync."""
        settings = self._settings
        settings.validate_auth()

        # Use persisted device_id so it stays stable across container restarts
        device_id = settings.bot_device_id or self._load_saved_device_id()

        self._client = create_client(
            homeserver=settings.matrix_homeserver,
            user_id=settings.matrix_user,
            device_id=device_id,
            crypto_store_path=settings.crypto_store_path,
        )

        self._setup_verification_callbacks()
        await self._login()
        self._save_session()          # persist device_id for next restart
        await self._upload_keys()
        await self._initial_sync()

        self._ready.set()
        self._sync_task = asyncio.create_task(self._background_sync())
        logger.info("matrix_client_started", user_id=self._client.user_id, device_id=self._client.device_id)

    async def stop(self) -> None:
        """Graceful shutdown: cancel sync task and close client."""
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.close()
            logger.info("matrix_client_stopped")

    # ------------------------------------------------------------------
    # Session persistence (device_id stability)
    # ------------------------------------------------------------------

    def _load_saved_device_id(self) -> Optional[str]:
        """Return device_id from previous session, if available."""
        try:
            if SESSION_FILE.exists():
                data = json.loads(SESSION_FILE.read_text())
                device_id = data.get("device_id")
                if device_id:
                    logger.info("session_device_id_loaded", device_id=device_id)
                    return device_id
        except Exception as exc:
            logger.warning("session_load_failed", error=str(exc))
        return None

    def _save_session(self) -> None:
        """Persist device_id so the next restart reuses the same Matrix device."""
        client = self._client
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(json.dumps({"device_id": client.device_id}))
            logger.info("session_saved", device_id=client.device_id)
        except Exception as exc:
            logger.warning("session_save_failed", error=str(exc))

    # ------------------------------------------------------------------
    # SAS Verification (bot-initiated — old flow supported by matrix-nio)
    # ------------------------------------------------------------------

    def _setup_verification_callbacks(self) -> None:
        """Register to-device callbacks for SAS verification.

        New flow (Element sends request → bot sends ready → SAS starts):
        - UnknownToDeviceEvent catches m.key.verification.ready

        nio automatically handles KeyVerificationAccept and KeyVerificationMac.
        We handle KeyVerificationKey to log emojis and confirm.
        """
        client = self._client
        client.add_to_device_callback(self._on_unknown_to_device, UnknownToDeviceEvent)
        client.add_to_device_callback(self._on_verification_key, KeyVerificationKey)
        client.add_to_device_callback(self._on_verification_mac, KeyVerificationMac)
        client.add_to_device_callback(self._on_verification_cancel, KeyVerificationCancel)

    async def _on_unknown_to_device(self, event: UnknownToDeviceEvent) -> None:
        """Handle m.key.verification.ready — not a known nio event type."""
        if event.type != "m.key.verification.ready":
            return

        content = event.source.get("content", {})
        txn_id = content.get("transaction_id")
        if not txn_id or txn_id not in self._pending_verifications:
            return

        _, _, device = self._pending_verifications.pop(txn_id)
        client = self._client

        # Build Sas with the same txn_id and send m.key.verification.start
        sas = Sas(
            own_user=client.user_id,
            own_device=client.device_id,
            own_fp_key=client.olm.account.identity_keys["ed25519"],
            other_olm_device=device,
            transaction_id=txn_id,
        )
        client.olm.key_verifications[txn_id] = sas

        start_msg = sas.start_verification()
        await client.to_device(start_msg)
        logger.info("verification_start_sent", transaction_id=txn_id)

    async def _on_verification_key(self, event: KeyVerificationKey) -> None:
        """Emojis are available — log them, then schedule auto-confirm as a separate task."""
        sas = self._client.key_verifications.get(event.transaction_id)
        if not sas:
            logger.warning("verification_key_sas_not_found", txn=event.transaction_id)
            return

        emojis = sas.get_emoji()

        lines = [
            "",
            "╔══════════════════════════════════════════════════════════╗",
            "║          GERÄTEVERIFIKATION  /  DEVICE VERIFICATION      ║",
            "╠══════════════════════════════════════════════════════════╣",
            f"║  Gerät / Device : {event.sender:<39}║",
            f"║  Transaction ID : {event.transaction_id[:39]:<39}║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  EMOJIS ZUM VERGLEICHEN / EMOJIS TO COMPARE:            ║",
        ]
        for i, (emoji, label) in enumerate(emojis, 1):
            entry = f"  {i:2}. {emoji}  {label}"
            lines.append(f"║  {entry:<56}║")
        lines += [
            "╠══════════════════════════════════════════════════════════╣",
            "║  DE: Stimmen die Emojis in Element überein?              ║",
            "║      → Ja: In Element auf 'Sie stimmen überein' klicken  ║",
            "║      → Nein: Abbrechen! (möglicher Angriff)              ║",
            "║  EN: Do the emojis in Element match?                     ║",
            "║      → Yes: Click 'They match' in Element                ║",
            "║      → No:  Cancel! (possible attack)                    ║",
            "║                                                          ║",
            "║  Bot bestätigt automatisch / Bot auto-confirms ✓         ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
        ]
        print("\n".join(lines), flush=True)

        # Schedule the MAC confirmation as an independent task so it runs
        # OUTSIDE the current sync-processing chain — avoids any nested-request issues.
        asyncio.create_task(self._send_verification_mac(event.transaction_id))

    async def _send_verification_mac(self, transaction_id: str) -> None:
        """Send m.key.verification.mac to complete our side of the SAS handshake."""
        try:
            resp = await self._client.confirm_short_auth_string(transaction_id)
        except Exception as exc:
            logger.error(
                "verification_mac_exception",
                error=str(exc),
                transaction_id=transaction_id,
            )
            return

        if isinstance(resp, ToDeviceError):
            logger.error(
                "verification_mac_http_error",
                errcode=getattr(resp, "errcode", "?"),
                message=getattr(resp, "message", str(resp)),
                transaction_id=transaction_id,
            )
            return

        logger.info("verification_bot_confirmed", transaction_id=transaction_id)

        # Flush any additionally queued messages just in case
        if self._client.outgoing_to_device_messages:
            await self._client.send_to_device_messages()

    async def _on_verification_mac(self, event: KeyVerificationMac) -> None:
        """nio verifies the device. Log result and send m.key.verification.done."""
        sas = self._client.key_verifications.get(event.transaction_id)
        verified = bool(sas and sas.verified_devices)
        status = "✓  VERIFIZIERT / VERIFIED" if verified else "✗  FEHLGESCHLAGEN / FAILED"
        print(
            f"\n╔══════════════════════════════════════════════════════════╗\n"
            f"║  VERIFIZIERUNG ABGESCHLOSSEN / VERIFICATION COMPLETE     ║\n"
            f"║  {status:<56}║\n"
            f"║  Gerät / Device : {event.sender:<39}║\n"
            f"╚══════════════════════════════════════════════════════════╝\n",
            flush=True,
        )
        if verified:
            logger.info("device_verified", sender=event.sender, transaction_id=event.transaction_id)
            # nio does not send m.key.verification.done — but Element requires it
            # to complete the handshake, otherwise it times out waiting.
            device_id = sas.other_olm_device.id
            asyncio.create_task(
                self._send_verification_done(event.transaction_id, event.sender, device_id)
            )
        else:
            logger.warning("device_verification_failed", sender=event.sender, transaction_id=event.transaction_id)

    async def _send_verification_done(self, transaction_id: str, user_id: str, device_id: str) -> None:
        """Send m.key.verification.done — required by modern clients (Element) to finalize SAS."""
        done_msg = ToDeviceMessage(
            "m.key.verification.done",
            user_id,
            device_id,
            {"transaction_id": transaction_id},
        )
        try:
            resp = await self._client.to_device(done_msg)
        except Exception as exc:
            print(f"[VERIFICATION] done send exception: {exc}", flush=True)
            logger.error("verification_done_exception", error=str(exc), transaction_id=transaction_id)
            return

        if isinstance(resp, ToDeviceError):
            print(f"[VERIFICATION] done send failed: {resp}", flush=True)
            logger.error("verification_done_error", transaction_id=transaction_id)
        else:
            print(f"[VERIFICATION] ✓ done sent to {user_id}/{device_id}", flush=True)
            logger.info("verification_done_sent", user_id=user_id, device_id=device_id, transaction_id=transaction_id)

    async def _on_verification_cancel(self, event: KeyVerificationCancel) -> None:
        logger.warning(
            "verification_cancelled",
            sender=event.sender,
            reason=event.reason,
            transaction_id=event.transaction_id,
        )

    async def start_verification(self, user_id: str, device_id: str) -> dict:
        """Bot initiates SAS verification with a specific device.

        nio only supports the bot-initiated (old) flow.
        The user will see a verification request in Element and must accept it there.
        Watch docker logs for the emojis, compare with Element, then confirm in Element.
        """
        await self._ready.wait()
        client = self._client

        if not client.olm:
            raise RuntimeError("E2EE not available (no OLM)")

        # Ensure we have fresh keys for this user
        client.users_for_key_query.add(user_id)
        await client.keys_query()

        devices = {d.id: d for d in client.device_store.active_user_devices(user_id)}
        if not devices:
            raise RuntimeError(f"No devices found for {user_id}. Is the user known to the bot?")

        if device_id not in devices:
            known = list(devices.keys())
            raise RuntimeError(
                f"Device '{device_id}' not found for {user_id}. "
                f"Known device IDs: {known}"
            )

        device = devices[device_id]

        if device.verified:
            client.unverify_device(device)
            logger.info(
                "device_unverified_for_reverification",
                user_id=user_id,
                device_id=device_id,
            )

        # New flow: send m.key.verification.request, wait for ready, then start SAS
        txn_id = str(uuid.uuid4())
        request_msg = ToDeviceMessage(
            "m.key.verification.request",
            user_id,
            device_id,
            {
                "from_device": client.device_id,
                "methods": ["m.sas.v1"],
                "timestamp": int(time.time() * 1000),
                "transaction_id": txn_id,
            },
        )
        await client.to_device(request_msg)

        # Store so _on_unknown_to_device can pick it up when ready arrives
        self._pending_verifications[txn_id] = (user_id, device_id, device)

        logger.info(
            "verification_request_sent",
            user_id=user_id,
            device_id=device_id,
            transaction_id=txn_id,
        )

        return {
            "status": "verification_requested",
            "transaction_id": txn_id,
            "instructions": (
                "1. Accept the verification request in Element. "
                "2. Watch 'docker logs matrix-e2ee-bot' for the emojis. "
                "3. Compare with Element and confirm there."
            ),
        }

    async def list_user_devices(self, user_id: str) -> dict:
        """Return all known devices for a user (queries homeserver for fresh data)."""
        await self._ready.wait()
        client = self._client
        client.users_for_key_query.add(user_id)
        try:
            await client.keys_query()
        except Exception:
            pass  # user might already be up-to-date
        devices = list(client.device_store.active_user_devices(user_id))
        return {
            "user_id": user_id,
            "devices": [
                {
                    "device_id": d.id,
                    "display_name": d.display_name,
                    "verified": d.verified,
                    "ed25519_key": d.ed25519,
                }
                for d in devices
            ],
        }

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        client = self._client
        settings = self._settings

        if settings.matrix_access_token:
            client.access_token = settings.matrix_access_token
            client.user_id = settings.matrix_user
            self._logged_in = True
            logger.info("matrix_login_token", user_id=client.user_id)
            return

        # login() internally passes self.device_id to the server,
        # so the server reuses the same device session when device_id is set.
        resp = await client.login(
            password=settings.matrix_password,
            device_name=settings.bot_display_name,
        )
        if isinstance(resp, LoginError):
            raise RuntimeError(f"Matrix login failed: {resp.message}")

        self._logged_in = True
        logger.info("matrix_login_password", user_id=client.user_id, device_id=client.device_id)

        try:
            await client.set_displayname(settings.bot_display_name)
        except Exception as exc:
            logger.warning("set_displayname_failed", error=str(exc))

    async def _upload_keys(self) -> None:
        client = self._client
        if not client.olm:
            logger.warning("olm_not_available_skipping_key_upload")
            return

        if not client.should_upload_keys:
            logger.info("keys_upload_not_needed")
            return

        resp = await client.keys_upload()
        if isinstance(resp, KeysUploadResponse):
            self._e2ee_enabled = True
            counts = getattr(resp, "one_time_key_counts", getattr(resp, "one_time_keys_counts", {}))
            logger.info("keys_uploaded", one_time_keys=counts)
        else:
            logger.warning("keys_upload_failed", response=str(resp))

    async def _initial_sync(self) -> None:
        resp = await self._client.sync(timeout=30000, full_state=True)
        if isinstance(resp, SyncError):
            raise RuntimeError(f"Initial sync failed: {resp.message}")
        logger.info("initial_sync_done")

    # ------------------------------------------------------------------
    # Background sync loop
    # ------------------------------------------------------------------

    async def _background_sync(self) -> None:
        interval_ms = self._settings.sync_interval * 1000
        logger.info("background_sync_started", interval_seconds=self._settings.sync_interval)
        while True:
            try:
                resp = await self._client.sync(
                    timeout=interval_ms,
                    full_state=False,
                )
                if isinstance(resp, SyncError):
                    logger.warning("sync_error", message=resp.message)
                else:
                    # Flush queued to-device messages (e.g. verification key shares)
                    # send_to_device_messages() is normally only called by sync_forever()
                    if self._client.outgoing_to_device_messages:
                        await self._client.send_to_device_messages()
                    if self._client.olm and self._client.should_upload_keys:
                        await self._upload_keys()
            except asyncio.CancelledError:
                logger.info("background_sync_cancelled")
                return
            except Exception as exc:
                logger.error("background_sync_exception", error=str(exc))
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # API operations
    # ------------------------------------------------------------------

    async def send_message(
        self,
        room_id: str,
        message: str,
        msgtype: str = "m.text",
    ) -> dict:
        """Send a (potentially encrypted) message to a room."""
        await self._ready.wait()
        client = self._client

        content = {"msgtype": msgtype, "body": message}

        room = client.rooms.get(room_id)
        encrypted = room.encrypted if room else False

        try:
            resp = await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
                ignore_unverified_devices=encrypted,
            )
        except OlmUnverifiedDeviceError:
            resp = await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
                ignore_unverified_devices=True,
            )

        if isinstance(resp, RoomSendError):
            raise RuntimeError(f"Send failed: {resp.message}")

        logger.info("message_sent", room_id=room_id, event_id=resp.event_id, encrypted=encrypted)
        return {"status": "sent", "event_id": resp.event_id, "encrypted": encrypted}

    async def join_room(self, room_id: str) -> dict:
        """Join a Matrix room."""
        await self._ready.wait()
        resp = await self._client.join(room_id)
        if isinstance(resp, JoinError):
            raise RuntimeError(f"Join failed: {resp.message}")
        logger.info("room_joined", room_id=room_id)
        return {"status": "joined", "room_id": room_id}

    async def create_room(
        self,
        name: str,
        topic: Optional[str] = None,
        invite: Optional[list[str]] = None,
        encrypted: bool = True,
    ) -> dict:
        """Create a new Matrix room."""
        await self._ready.wait()

        initial_state = []
        if encrypted:
            initial_state.append({
                "type": "m.room.encryption",
                "state_key": "",
                "content": {"algorithm": "m.megolm.v1.aes-sha2"},
            })

        resp = await self._client.room_create(
            name=name,
            topic=topic or "",
            invite=invite or [],
            initial_state=initial_state,
        )
        if isinstance(resp, RoomCreateError):
            raise RuntimeError(f"Create room failed: {resp.message}")

        logger.info("room_created", room_id=resp.room_id, encrypted=encrypted)
        return {"status": "created", "room_id": resp.room_id}

    async def invite_user(self, room_id: str, user_id: str) -> dict:
        """Invite a user to a room."""
        await self._ready.wait()
        resp = await self._client.room_invite(room_id, user_id)
        if isinstance(resp, RoomInviteError):
            raise RuntimeError(f"Invite failed: {resp.message}")
        logger.info("user_invited", room_id=room_id, user_id=user_id)
        return {"status": "invited", "room_id": room_id, "user_id": user_id}

    async def get_rooms(self) -> dict:
        """Return list of joined rooms."""
        await self._ready.wait()
        rooms = []
        for room_id, room in self._client.rooms.items():
            rooms.append({
                "room_id": room_id,
                "name": room.display_name or room_id,
                "encrypted": room.encrypted,
                "member_count": room.member_count,
            })
        return {"rooms": rooms}

    def health(self) -> dict:
        """Return health/status information."""
        client = self._client
        return {
            "status": "ok" if (self._logged_in and self._ready.is_set()) else "initializing",
            "user_id": client.user_id if client else None,
            "device_id": client.device_id if client else None,
            "logged_in": self._logged_in,
            "e2ee_enabled": self._e2ee_enabled,
            "sync_running": self._sync_task is not None and not self._sync_task.done(),
        }
