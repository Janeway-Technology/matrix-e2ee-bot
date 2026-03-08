# Matrix E2EE Bot

A production-ready Matrix bot microservice with full **End-to-End Encryption (E2EE)**, exposed as a simple REST API. Framework-agnostic — works with n8n, Make.com, curl, or any HTTP client.

## The Idea

Matrix is one of the few open, federated messaging protocols that supports genuine end-to-end encryption. However, integrating Matrix E2EE into automation workflows (n8n, webhooks, scripts) is painful: every client library requires managing Olm/Megolm crypto state, device verification, key storage, and sync loops.

This project wraps all of that complexity into a single **self-hosted Docker container** with a dead-simple REST API. Your automation tool just calls `POST /send` with a room ID and message — the bot handles encryption, key management, and Matrix protocol details transparently.

**Use cases:**
- Send encrypted alerts from monitoring systems (Grafana, Prometheus, Checkmk)
- Encrypted notifications from CI/CD pipelines
- Secure message dispatch from n8n / Make.com workflows
- Any scenario where you need programmatic, encrypted Matrix messaging

---

## Security

### What this protects
- **End-to-end encrypted messages** using the Matrix Megolm protocol — the homeserver operator cannot read message content
- **Device verification via SAS** (Short Authentication String / emoji comparison) — proves the bot's identity cryptographically and prevents MITM attacks
- **Stable device identity** — the bot's Olm identity key is generated once and persisted in a Docker volume; it never changes across restarts, so re-verification is not needed after updates
- **API authentication** via Bearer token — all write endpoints require a secret token

### What this does NOT protect
- **Metadata**: the homeserver sees who talks to whom, room membership, and timestamps — only message content is encrypted
- **The API endpoint itself** is plain HTTP by default — run it behind a reverse proxy with TLS if exposed beyond localhost
- **The Bearer token** is symmetric — keep it secret and rotate it if compromised

### Threat model
This bot is designed for **self-hosted, trusted environments** (your own server, private Docker stack). The REST API should never be exposed to the public internet without TLS and network-level access control. The crypto store volume contains your device's private keys — back it up and protect it like a password.

---

## Requirements

- Docker + Docker Compose
- A Matrix account for the bot (self-hosted homeserver or matrix.org)
- Any Matrix client for the human side (Element Desktop / Web / Mobile recommended)

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Janeway-Technology/matrix-e2ee-bot.git
cd matrix-e2ee-bot
```

### 2. Configure

```bash
cp .env.example .env
$EDITOR .env
```

Fill in at minimum:

| Variable | Description |
|---|---|
| `MATRIX_HOMESERVER` | Your homeserver URL, e.g. `https://matrix.example.com` |
| `MATRIX_USER` | Bot account Matrix ID, e.g. `@bot:example.com` |
| `MATRIX_PASSWORD` | Bot account password (or use `MATRIX_ACCESS_TOKEN`) |
| `API_BEARER_TOKEN` | A strong random secret — used to authenticate all API calls |

### 3. Start

```bash
docker compose up -d
```

Check that it started correctly:

```bash
curl http://localhost:5001/health
```

```json
{
  "status": "ok",
  "user_id": "@bot:example.com",
  "device_id": "ABCXYZ",
  "logged_in": true,
  "e2ee_enabled": true,
  "sync_running": true
}
```

### 4. Verify the bot's device (one-time, strongly recommended)

Device verification proves the bot is who it claims to be. You only need to do this once — the verification state persists across container restarts.

**Step 1:** Find the bot's device ID (shown in the `/health` response, or via the devices endpoint):

```bash
# URL-encode @ as %40 and : as %3A
curl "http://localhost:5001/devices/%40bot%3Aexample.com" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Step 2:** Start the SAS verification from the API:

```bash
curl -X POST http://localhost:5001/verify-device \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "@bot:example.com", "device_id": "ABCXYZ"}'
```

**Step 3:** A verification request appears in Element. Click **Accept**.

**Step 4:** Compare the 7 emojis shown in Element with those in the bot logs:

```bash
docker logs matrix-e2ee-bot --follow
```

**Step 5:** If the emojis match, click **They match** in Element. The bot confirms automatically — both devices are now verified.

---

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `MATRIX_HOMESERVER` | yes | — | e.g. `https://matrix.example.com` |
| `MATRIX_USER` | yes | — | e.g. `@bot:example.com` |
| `MATRIX_PASSWORD` | one of | — | Bot account password |
| `MATRIX_ACCESS_TOKEN` | one of | — | Pre-existing access token (alternative to password) |
| `BOT_DISPLAY_NAME` | no | `Matrix Bot` | Display name shown in rooms |
| `BOT_DEVICE_ID` | no | auto | Fix the device ID (useful for stable verification) |
| `API_BEARER_TOKEN` | yes | — | Secret token for API auth — never commit this |
| `CRYPTO_STORE_PATH` | no | `/app/data/crypto_store` | Path to the Olm/Megolm key database |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `SYNC_INTERVAL` | no | `30` | Background sync interval in seconds |

---

## API Reference

All endpoints except `GET /health` require:

```
Authorization: Bearer <API_BEARER_TOKEN>
Content-Type: application/json
```

---

### `GET /health`

Returns bot status. No authentication required.

```bash
curl http://localhost:5001/health
```

```json
{
  "status": "ok",
  "user_id": "@bot:example.com",
  "device_id": "ABCXYZ",
  "logged_in": true,
  "e2ee_enabled": true,
  "sync_running": true
}
```

---

### `POST /send`

Send a message to a room. Automatically encrypted if the room has E2EE enabled.

```bash
curl -X POST http://localhost:5001/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": "!abc123:example.com",
    "message": "Hello from the bot!",
    "msgtype": "m.text"
  }'
```

| Field | Required | Description |
|---|---|---|
| `room_id` | yes | Matrix room ID (`!...`) |
| `message` | yes | Message text |
| `msgtype` | no | `m.text` (default) \| `m.notice` \| `m.emote` |

```json
{"status": "sent", "event_id": "$abc123", "encrypted": true}
```

---

### `POST /join`

Join a Matrix room.

```bash
curl -X POST http://localhost:5001/join \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"room_id": "!abc123:example.com"}'
```

```json
{"status": "joined", "room_id": "!abc123:example.com"}
```

---

### `POST /create-room`

Create a new Matrix room, optionally with E2EE enabled.

```bash
curl -X POST http://localhost:5001/create-room \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alerts",
    "topic": "System notifications",
    "invite": ["@alice:example.com"],
    "encrypted": true
  }'
```

| Field | Required | Description |
|---|---|---|
| `name` | yes | Room display name |
| `topic` | no | Room topic |
| `invite` | no | List of Matrix IDs to invite on creation |
| `encrypted` | no | `true` (default) — enable E2EE from the start |

```json
{"status": "created", "room_id": "!xyz:example.com"}
```

---

### `POST /invite`

Invite a user to an existing room.

```bash
curl -X POST http://localhost:5001/invite \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": "!abc123:example.com",
    "user_id": "@alice:example.com"
  }'
```

```json
{"status": "invited", "room_id": "!abc123:example.com", "user_id": "@alice:example.com"}
```

---

### `GET /rooms`

List all rooms the bot has joined.

```bash
curl http://localhost:5001/rooms \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "rooms": [
    {
      "room_id": "!abc123:example.com",
      "name": "Alerts",
      "encrypted": true,
      "member_count": 2
    }
  ]
}
```

---

### `GET /devices/{user_id}`

List all known devices for a Matrix user. Used to find the `device_id` before starting verification.

```bash
# URL-encode @ as %40 and : as %3A
curl "http://localhost:5001/devices/%40alice%3Aexample.com" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "user_id": "@alice:example.com",
  "devices": [
    {
      "device_id": "ABCXYZ",
      "display_name": "Element Desktop",
      "verified": true,
      "ed25519_key": "abc123..."
    }
  ]
}
```

---

### `POST /verify-device`

Start bot-initiated SAS (emoji) verification with a specific device.

```bash
curl -X POST http://localhost:5001/verify-device \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "@alice:example.com",
    "device_id": "ABCXYZ"
  }'
```

```json
{
  "status": "verification_requested",
  "transaction_id": "abc-123-...",
  "instructions": "1. Accept the verification request in Element. 2. Watch 'docker logs matrix-e2ee-bot' for the emojis. 3. Compare with Element and confirm there."
}
```

**Full verification flow:**
1. API call → bot sends `m.key.verification.request` to the device
2. User accepts in Element → bot sends `m.key.verification.start`
3. Both sides exchange keys and compute the same 7 emojis
4. Emojis appear in `docker logs` AND in Element simultaneously
5. User clicks **They match** in Element → Element sends its MAC
6. Bot auto-confirms, sends its MAC + `m.key.verification.done`
7. Verification complete — device is marked trusted in the crypto store

---

## n8n Integration Example

Use an **HTTP Request** node:

- **Method:** POST
- **URL:** `http://your-server:5001/send`
- **Header Auth:** `Authorization: Bearer YOUR_TOKEN`
- **Body (JSON):**

```json
{
  "room_id": "!abc123:example.com",
  "message": "{{ $json.alert_message }}"
}
```

---

## Architecture

```
app/
├── main.py            # FastAPI app + lifespan (startup / shutdown)
├── config.py          # Pydantic settings from environment variables
├── matrix_client.py   # MatrixClientManager: login, sync, E2EE, SAS verification
├── crypto_manager.py  # Olm/Megolm client factory + SqliteStore setup
├── api/
│   ├── routes.py      # REST endpoint definitions
│   ├── auth.py        # Bearer token dependency
│   └── models.py      # Pydantic request/response models
└── utils/
    ├── logger.py      # Structured JSON logging (structlog)
    └── validators.py  # Matrix ID format validators
```

**E2EE internals:**
- Uses [matrix-nio](https://github.com/poljar/matrix-nio) with libolm for Olm/Megolm crypto
- On first start: generates device identity, uploads one-time keys to homeserver
- Background sync loop processes incoming to-device messages (key shares, verification events)
- Crypto state is persisted in a SQLite database inside the Docker volume
- Device ID is saved separately in `session.json` so identity survives container restarts

---

## Persistence

The Docker volume `crypto_store` contains:

| File | Purpose |
|---|---|
| `session.json` | Saved device ID — ensures stable identity across restarts |
| `crypto_store/*.db` | Olm device keys, Megolm sessions, sync tokens |

**Do not delete this volume** unless you want to reset the bot's identity and re-verify all devices.

Backup:
```bash
docker run --rm \
  -v matrix-e2ee-bot_crypto_store:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/crypto_backup.tar.gz /data
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `"status": "initializing"` | Bot still syncing or login failed | `docker logs matrix-e2ee-bot` |
| `401` on API calls | Wrong `API_BEARER_TOKEN` | Verify token in `.env` matches your header |
| Messages arrive unencrypted | Room not encrypted | Create room with `"encrypted": true` |
| Verification times out | `done` message not sent | Check logs for `verification_done_*` entries |
| Container restart loop | Crypto store permissions | Check Docker volume is writable by container user |
| Bot loses verification after restart | Volume deleted or not mounted | Verify `docker compose` volume config |

---

## Interactive API Docs

When running:

- **Swagger UI:** `http://localhost:5001/docs`
- **ReDoc:** `http://localhost:5001/redoc`

---

## License

MIT
