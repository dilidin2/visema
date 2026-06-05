# AGENTS.md — Visema

> **Visema** is a local Twitch bot that lets viewers spend Channel Points to display a GIF or play an audio clip on stream via an OBS Browser Source overlay. It is part of a family of local bots (Melos, Phonema) and follows the same local-first, no-cloud design philosophy.

---

## Project Purpose

A viewer redeems one of two Channel Points rewards on Twitch:

- **"Show a GIF"** — submits a GIF URL from Giphy; the GIF is shown on the OBS overlay for a configurable duration.
- **"Play a Sound"** — submits a sound name; the bot looks it up in a local audio library curated by the streamer and plays it through the OBS overlay.

Visema validates GIF URLs against Giphy's CDN domains, and resolves audio requests against a local `sounds/` folder. Both go through a single unified queue and are processed one at a time.

---

## Repository Layout

```
visema/
│
├── .env                        # secrets (never commit)
├── config.yaml                 # runtime settings (see Configuration section)
├── requirements.txt
├── README.md
├── AGENTS.md                   # this file
│
├── sounds/                     # local audio library — streamer adds MP3/OGG/WAV files here
│   └── (e.g. vine_boom.mp3, bruh.mp3, airhorn.ogg ...)
│
├── visema/
│   ├── __init__.py
│   │
│   ├── main.py                 # entrypoint: wires everything together and starts the event loop
│   │
│   ├── twitch/
│   │   ├── __init__.py
│   │   ├── auth.py             # OAuth2 flow for both accounts, token refresh
│   │   ├── eventsub.py         # EventSub WebSocket listener → fires on_redemption()
│   │   └── chat.py             # bot_channel chat listener for !gif and !sound commands
│   │
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py              # FastAPI: HTTP routes, static file serving, WebSocket endpoint
│   │   └── ws_manager.py       # tracks active WebSocket connections (OBS browser sources)
│   │
│   ├── overlay/
│   │   ├── index.html          # the page OBS loads as a Browser Source
│   │   ├── overlay.js          # receives WS events, renders GIF or plays audio with fade
│   │   └── overlay.css         # transparent background, positioning, animations
│   │
│   ├── media/
│   │   ├── __init__.py
│   │   ├── validator.py        # GIF URL validation + audio name→file resolution
│   │   └── queue.py            # unified FIFO queue for GIF + audio events with cooldown
│   │
│   └── utils/
│       ├── __init__.py
│       └── config.py           # loads .env and config.yaml, exposes a typed Settings object
│
└── tests/
    ├── test_validator.py
    └── test_queue.py
```

---

## Two-Account Design

Visema separates two Twitch identities, matching the pattern used by Melos and Phonema:

| Role | Config key | Purpose |
|---|---|---|
| **Broadcaster account** | `target_channel` | The streamer's main channel. EventSub listens for redemptions on this channel. |
| **Bot account** | `bot_channel` | A dedicated bot account. Sends chat messages (confirmations, errors, command responses). |

Both accounts must be authenticated. `auth.py` handles two separate OAuth2 flows and stores/refreshes both tokens independently.

The **broadcaster account** needs the OAuth scopes:
- `channel:read:redemptions`
- `channel:manage:redemptions` (to fulfill or cancel a redemption programmatically)

The **bot account** needs:
- `chat:edit` (to send messages)
- `chat:read` (to listen for `!gif` and `!sound` commands)

---

## Configuration

### `.env`  *(secrets — never commit)*

```env
# Twitch app credentials (from dev.twitch.tv)
TWITCH_CLIENT_ID=your_client_id
TWITCH_CLIENT_SECRET=your_client_secret

# OAuth tokens — populated automatically by auth.py on first run
BROADCASTER_ACCESS_TOKEN=
BROADCASTER_REFRESH_TOKEN=
BOT_ACCESS_TOKEN=
BOT_REFRESH_TOKEN=
```

### `config.yaml`  *(safe to commit)*

```yaml
twitch:
  target_channel: "your_twitch_username"     # broadcaster — where redemptions happen
  bot_channel: "your_bot_username"           # bot — sends chat messages
  reward_gif: "Show a GIF"                   # exact name of the GIF Channel Points reward
  reward_sound: "Play a Sound"               # exact name of the audio Channel Points reward

gif:
  allowed_domains:
    - "i.giphy.com"
    - "media.giphy.com"
    - "media0.giphy.com"
    - "media1.giphy.com"
    - "media2.giphy.com"
    - "media3.giphy.com"
    - "media4.giphy.com"
  display_duration_seconds: 8
  cooldown_seconds: 3
  max_queue_size: 5
  size_percent: 40                           # GIF width as % of OBS canvas width

audio:
  sounds_dir: "sounds"                       # path to the local audio library folder
  allowed_extensions:
    - ".mp3"
    - ".ogg"
    - ".wav"
  volume: 1.0                                # 0.0 – 1.0, applied in overlay.js
  cooldown_seconds: 3
  max_queue_size: 5                          # shared with gif queue (global cap)

overlay:
  port: 9876
  position: "center"                         # center | bottom-left | bottom-right | top-left | top-right

commands:
  gif_response: >
    🎬 To use "Show a GIF", paste a direct GIF link from Giphy (giphy.com).
    Right-click any GIF → "Copy Image Address". The link must start with
    i.giphy.com or media.giphy.com. SFW only — invalid links are refunded.
  sound_response: >
    🔊 To use "Play a Sound", type the name of a sound from the list.
    Use !soundlist to see all available sounds.
  soundlist_response: "auto"                 # "auto" = generated at runtime from sounds/ folder
```

---

## Whitelisted Domains — GIF

Visema only accepts **direct CDN links** from Giphy. No page URLs, no redirects.

| Domain | How to get the link |
|---|---|
| `i.giphy.com` | Go to [giphy.com](https://giphy.com), find a GIF, right-click it → **"Copy Image Address"**. The URL will look like `https://i.giphy.com/media/.../giphy.gif`. |
| `media.giphy.com` | Same as above; some GIFs resolve to this subdomain instead. |
| `media0.giphy.com` – `media4.giphy.com` | Numbered CDN shards used by Giphy internally. Same direct-link behaviour. |

> **What to reject:** any URL whose hostname is exactly `giphy.com` (without a subdomain) is a page URL, not a raw GIF — reject it and tell the viewer to right-click and copy the image address instead.

No API keys are required. Giphy's CDN links are publicly accessible and do not need authentication.

---

## Local Audio Library (`sounds/`)

Audio is **not user-supplied at runtime**. The streamer populates the `sounds/` folder manually before starting the bot. Viewers then request sounds by name — they cannot inject arbitrary URLs.

### How it works

1. The streamer drops audio files into `sounds/` (e.g. `vine_boom.mp3`, `bruh.mp3`, `airhorn.ogg`).
2. On startup, `media/validator.py` scans `sounds/` and builds an in-memory index: `{ "vine_boom": Path("sounds/vine_boom.mp3"), ... }`. Keys are filenames lowercased, with the extension stripped.
3. When a viewer redeems "Play a Sound" and types e.g. `vine boom` or `vine_boom`, the validator normalises the input (lowercase, strip punctuation, replace spaces with underscores) and looks it up in the index.
4. If found → the **local file path** (not a URL) is sent to the overlay via WebSocket as a served static route: `{ "type": "audio", "src": "/sounds/vine_boom.mp3", "volume": 1.0 }`.
5. FastAPI serves the `sounds/` directory as a static mount at `/sounds`, so `overlay.js` can fetch the file directly from `http://localhost:9876/sounds/vine_boom.mp3`.

### Naming convention

- Use lowercase filenames with underscores: `vine_boom.mp3`, `sad_trombone.mp3`.
- No spaces in filenames — the validator normalises viewer input to match this pattern.
- Supported formats: `.mp3`, `.ogg`, `.wav`.

### `!soundlist` command

When a viewer types `!soundlist` in chat, the bot responds with the full list of available sound names, generated at runtime from the `sounds/` index. If the list is long (> 10 items), the bot posts it in a single message as a comma-separated list. Example response:

```
[Visema] 🔊 Available sounds: airhorn, bruh, vine_boom, sad_trombone, nani, myname_jeff, ...
```

The `soundlist_response` config key can be set to `"auto"` (default, generates from folder) or a hardcoded string to override it.

---

## Chat Commands

`twitch/chat.py` listens on the broadcaster's channel using the bot account. All commands are read-only — they do not trigger any overlay or queue action.

| Command | Who can use | Response |
|---|---|---|
| `!gif` | Everyone | How to find and copy a Giphy direct link. |
| `!sound` | Everyone | How to use the sound redeem + reminder to use `!soundlist`. |
| `!soundlist` | Everyone | Auto-generated list of all sound names currently in `sounds/`. |

All response strings are defined in `config.yaml` under `commands:` and can be edited without touching the code.

---

## Data Flow (step by step)

```
── GIF REDEEM ──────────────────────────────────────────────────────────────────

1. Viewer redeems "Show a GIF" on Twitch, pastes a Giphy direct link as input.

2. eventsub.py receives: channel.channel_points_custom_reward_redemption.add
   Identifies the reward as type "gif".

3. media/validator.py checks:
   a. URL is well-formed.
   b. Hostname is in config.gif.allowed_domains (i.giphy.com, media*.giphy.com).
   c. Hostname is NOT bare "giphy.com" (page URL — reject with helpful message).
   → Invalid: redemption CANCELLED (points refunded), bot posts reason in chat.
   → Valid: proceed with the URL as-is (no resolution step needed).

4. media/queue.py enqueues { type: "gif", url: "<cdn_url>", duration: 8 }.
   - Queue full → CANCEL, refund.
   - Otherwise → FULFILL redemption immediately.

5. Queue worker dequeues, calls ws_manager.broadcast():
   { "type": "gif", "url": "https://i.giphy.com/...", "duration": 8 }

6. overlay.js receives the message:
   - Injects <img src="url"> into the DOM.
   - Fades in, holds for `duration` seconds, fades out, removes element.

7. After cooldown_seconds, next queue item is processed.

── AUDIO REDEEM ────────────────────────────────────────────────────────────────

1. Viewer redeems "Play a Sound" on Twitch, types a sound name as input
   (e.g. "vine boom", "vine_boom", "VINE BOOM" — all equivalent).

2. eventsub.py receives the event. Identifies the reward as type "audio".

3. media/validator.py normalises the input:
   lowercase → strip punctuation → replace spaces with underscores
   Then looks up the normalised key in the in-memory sounds index.
   → Not found: redemption CANCELLED (points refunded), bot replies with
     "Sound not found. Use !soundlist to see available sounds."
   → Found: proceed with the resolved file path.

4. media/queue.py enqueues { type: "audio", src: "/sounds/vine_boom.mp3", volume: 1.0 }.
   - Queue full → CANCEL, refund.
   - Otherwise → FULFILL redemption immediately.

5. Queue worker dequeues, calls ws_manager.broadcast():
   { "type": "audio", "src": "/sounds/vine_boom.mp3", "volume": 1.0 }

6. overlay.js receives the message:
   - Creates an <audio> element, sets src to http://localhost:9876/sounds/vine_boom.mp3
   - Sets volume, calls .play().
   - On "ended" event: removes the element, signals the queue worker.

7. After cooldown_seconds, next queue item is processed.
```

---

## OBS Integration

1. In OBS, add a **Browser Source**.
2. Set the URL to: `http://localhost:9876/overlay`
3. Set width/height to match your canvas (e.g. 1920 × 1080).
4. Enable **"Shutdown source when not visible"** = OFF.
5. Enable **"Refresh browser when scene becomes active"** = ON (optional but recommended).
6. Check **"Allow transparency"** so the overlay background is invisible.

The overlay page connects automatically to the local WebSocket at `ws://localhost:9876/ws` on load. No manual configuration in OBS beyond pointing it at the URL.

> **Audio note:** OBS Browser Source uses an embedded Chromium engine. Audio played via the Web Audio API inside the Browser Source routes through OBS's audio pipeline and appears as a Desktop Audio or Browser Source audio track. Make sure the Browser Source audio track is unmuted in OBS's Audio Mixer.

---

## Running the Bot

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add sound files to the sounds/ folder
cp my_sounds/*.mp3 sounds/

# 3. First run — triggers OAuth flows for both accounts in the browser
python -m visema.main --setup

# 4. Normal run
python -m visema.main
```

On first run, `auth.py` opens two browser tabs in sequence (broadcaster account, then bot account) for OAuth authorization. Tokens are saved back to `.env` automatically.

---

## Key Dependencies

| Package | Version | Role |
|---|---|---|
| `twitchAPI` | ≥ 4.5.0 | EventSub WebSocket, Twitch API calls, OAuth |
| `fastapi` | latest | HTTP server, static file serving, WebSocket endpoint |
| `uvicorn[standard]` | latest | ASGI server to run FastAPI |
| `websockets` | latest | Low-level WebSocket support (used by twitchAPI) |
| `python-dotenv` | latest | Load `.env` into environment |
| `pyyaml` | latest | Parse `config.yaml` |

No external API keys are required beyond the Twitch app credentials.

---

## Module Responsibilities

### `visema/main.py`
- Loads settings via `utils/config.py`.
- Starts the FastAPI server (uvicorn) in a background thread.
- Initializes both Twitch OAuth sessions.
- Starts the EventSub WebSocket listener and the chat command listener.
- Runs the asyncio event loop.

### `visema/twitch/auth.py`
- Handles OAuth2 authorization code flow for two separate accounts.
- Persists and auto-refreshes access tokens in `.env`.
- Exposes two authenticated `Twitch` client instances: `broadcaster_client` and `bot_client`.

### `visema/twitch/eventsub.py`
- Subscribes to `channel.channel_points_custom_reward_redemption.add` on the broadcaster's channel.
- Matches events against both `reward_gif` and `reward_sound` names from config.
- Sets the payload `type` field accordingly and delegates to `media/validator.py` and `media/queue.py`.
- Uses `broadcaster_client` to fulfill or cancel redemptions.
- Uses `bot_client` to post chat feedback.

### `visema/twitch/chat.py`
- Uses the bot account to listen for `!gif`, `!sound`, and `!soundlist` in the broadcaster's chat.
- For `!soundlist`: reads the live sounds index from `media/validator.py` and formats the response.
- Does not interact with the queue or overlay.

### `visema/server/app.py`
- `GET /overlay` → serves `overlay/index.html`.
- `GET /static/{file}` → serves `overlay.js` and `overlay.css`.
- `StaticFiles` mount at `/sounds` → serves the `sounds/` directory.
- `WebSocket /ws` → endpoint that OBS Browser Sources connect to.

### `visema/server/ws_manager.py`
- Maintains a set of active WebSocket connections.
- `broadcast(payload: dict)` sends a JSON message to all connected clients.
- Handles connect/disconnect cleanly.

### `visema/media/validator.py`
- On startup: scans `sounds/` and builds `sounds_index: dict[str, Path]`.
- `validate_gif(url: str) -> str | None` — returns the URL unchanged if valid, None otherwise.
- `validate_audio(name: str) -> Path | None` — normalises input, looks up in `sounds_index`, returns Path or None.
- Both functions read settings from `Settings`.

### `visema/media/queue.py`
- Single async FIFO queue (`asyncio.Queue`) for both GIF and audio events.
- Each item: `{ "type": "gif"|"audio", ... }`.
- Worker coroutine dequeues, calls `ws_manager.broadcast()`, then awaits completion signal from the overlay (via a WebSocket ack) or a timeout fallback, then waits `cooldown_seconds`.
- Respects `max_queue_size`.

### `visema/utils/config.py`
- Loads `.env` with `python-dotenv`.
- Parses `config.yaml` with `pyyaml`.
- Exposes a single `Settings` dataclass/object imported by all other modules.

---

## Coding Conventions

- All async code uses `asyncio`. Do not mix threading except for the uvicorn server thread in `main.py`.
- All Twitch API calls go through `twitchAPI` — do not call the Twitch REST API directly.
- Log with the standard `logging` module. Use `logging.getLogger(__name__)` in each module.
- Never hardcode credentials. Always read from `Settings`.
- The overlay (`index.html`, `overlay.js`, `overlay.css`) must work inside OBS's embedded Chromium with no external CDN dependencies — inline or bundle everything.
- `overlay.js` handles both `type: "gif"` and `type: "audio"` payloads from the same WebSocket connection.
- When the audio `"ended"` event fires in `overlay.js`, send a `{ "ack": "audio_done" }` message back over the WebSocket so `queue.py` knows to start the cooldown timer rather than relying on a fixed timeout.

---

## Extending the Bot

- **Skip command**: add a `!visemaskip` chat command (moderator/broadcaster only) that clears the current item and advances the queue.
- **Per-user cooldown**: track last redemption time per user in a dict in `queue.py` to prevent spam from a single viewer.
- **Blocklist**: add a `blocked_users` list in `config.yaml`; redemptions from those users are auto-cancelled.
- **Hot-reload sounds**: watch `sounds/` for file changes with `watchfiles` and rebuild the index without restarting the bot.
- **Other bots (Melos, Phonema)**: share `utils/config.py` and `twitch/auth.py` patterns for consistency across the bot family.
