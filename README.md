# Visema

Twitch Channel Points overlay bot — let viewers spend points to show GIFs or play sound clips on your stream via an OBS Browser Source. Fully local, no cloud dependencies.

![Visema](docs/img.png)

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

---

## What it does

Viewers redeem Channel Points rewards on Twitch to trigger on-stream media:

- **"Show a GIF"** — paste a direct Giphy link; the GIF appears on your OBS overlay for a configurable duration.
- **"Play a Sound"** — type a sound name from a local library; the clip plays through the OBS Browser Source.

Both reward types share a single FIFO queue with cooldown, so media never overlaps. Invalid requests are auto-cancelled and points refunded.

---

## Quick Start

> [!IMPORTANT]
> Python 3.10 or later is required. This project uses `uv` for dependency management.

```bash
# 1. Clone the repo
git clone https://github.com/matteo/visema.git
cd visema

# 2. Install dependencies (creates a .venv automatically)
uv sync

# 3. Copy example config and edit it
cp config.yaml.example config.yaml
# Edit config.yaml — set reward names to match your Twitch Channel Points rewards

# 4. Set up .env with your broadcaster ID
cp .env.example .env
# Edit .env — fill in TWITCH_BROADCASTER_ID (your numeric channel ID)

# 5. Add sound files to the sounds/ folder
cp my_sounds/*.mp3 sounds/

# 6. Run — first launch triggers Device Code authentication
uv run visema
```

On first run, Visema prints a device code and URL. Open the URL in a browser, enter the code, and authorize the app. Tokens are saved automatically for future runs.

---

## OBS Setup

1. In OBS, add a **Browser Source**.
2. Set URL to: `http://127.0.0.1:9876/overlay`
3. Set width/height to your canvas (e.g. 1920×1080).
4. Enable **"Allow transparency"**.
5. Disable **"Shutdown source when not visible"**.

The overlay connects automatically via WebSocket — no additional configuration needed.

> [!NOTE]
> Audio played through the Browser Source routes to OBS's audio pipeline. Make sure the Browser Source track is unmuted in the Audio Mixer.

---

## Configuration

### `.env` *(secrets — never commit)*

```ini
# Optional — set only if you fork with your own Twitch app
# TWITCH_CLIENT_ID=your_client_id_here

# Required — your numeric channel ID (not username!)
# Find it at: https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/
TWITCH_BROADCASTER_ID=123456789
```

### `config.yaml` *(safe to commit)*

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `twitch` | `reward_gif` | `"Mostra una GIF"` | Exact name of the GIF Channel Points reward |
| `twitch` | `reward_sound` | `"Suona Suono"` | Exact name of the sound Channel Points reward |
| `twitch` | `reward_gif_cost` | `500` | Points cost for GIF redeem |
| `twitch` | `reward_sound_cost` | `300` | Points cost for sound redeem |
| `gif` | `allowed_domains` | Giphy CDN domains | Domains accepted for GIF URLs |
| `gif` | `display_duration_seconds` | `8` | How long a GIF is shown (seconds) |
| `gif` | `cooldown_seconds` | `3` | Wait time between queue items |
| `gif` | `max_queue_size` | `5` | Maximum items in the queue |
| `gif` | `size_percent` | `40` | GIF width as % of overlay canvas |
| `audio` | `sounds_dir` | `"sounds"` | Path to local audio library folder |
| `audio` | `volume` | `1.0` | Playback volume (0.0–1.0) |
| `overlay` | `port` | `9876` | HTTP/WebSocket server port |
| `overlay` | `position` | `"center"` | Overlay position (`center`, `bottom-left`, etc.) |

---

## Dual-Account Mode

By default, Visema runs with a single Twitch account (the broadcaster). For separation of concerns, you can use a dedicated bot account for chat messages:

```bash
# First authenticate the broadcaster (single mode)
uv run visema

# Then run with a separate bot account
uv run visema --bot
```

The `--bot` flag requires the broadcaster to already be authenticated (`token_broadcaster.json` must exist). On first dual-account run, Visema triggers a second Device Code Flow for the bot.

---

## GIF URLs

Visema only accepts direct CDN links from Giphy — not page URLs.

**How viewers get a valid link:**
1. Go to [giphy.com](https://giphy.com) and find a GIF.
2. Right-click the GIF → **"Copy Image Address"**.
3. Paste the URL in the Channel Points redeem input.

Valid URLs start with `i.giphy.com` or `media*.giphy.com`. Page URLs like `giphy.com/gifs/...` are rejected automatically and points are refunded.

---

## Sound Library

Audio files are managed locally by the streamer — viewers cannot upload or inject arbitrary audio.

1. Place `.mp3`, `.ogg`, or `.wav` files in the `sounds/` folder.
2. On startup, Visema builds an index from filenames (lowercased, extension stripped).
3. Viewers request sounds by name — `"vine boom"`, `"vine_boom"`, and `"VINE BOOM"` all resolve to the same file.

Use the `!soundlist` chat command to see all available sounds.

---

## Chat Commands

All commands are read-only and respond in chat:

| Command | Description |
|---------|-------------|
| `!gif` | Instructions for finding a valid Giphy direct link |
| `!sound` | How to use the sound redeem + reminder to use `!soundlist` |
| `!soundlist` | Lists all available sounds from the `sounds/` folder |

Response text is configurable in `config.yaml` under the `commands:` section.

---

## Project Structure

```
visema/
├── .env                      # secrets (broadcaster ID, optional client credentials)
├── config.yaml               # runtime settings (reward names, queue, overlay)
├── pyproject.toml            # project metadata and dependencies
├── sounds/                   # local audio library — add MP3/OGG/WAV files here
│   ├── boom.mp3
│   └── oof.mp3
├── visema/
│   ├── main.py               # entrypoint — wires everything together
│   ├── twitch/
│   │   ├── auth.py           # Device Code Flow authentication, token persistence
│   │   ├── eventsub.py       # EventSub listener for Channel Points redemptions
│   │   └── chat.py           # EventSub-based chat command listener
│   ├── server/
│   │   ├── app.py            # FastAPI: HTTP routes, static files, WebSocket
│   │   └── ws_manager.py     # active WebSocket connection tracking and broadcasting
│   ├── overlay/
│   │   ├── index.html        # OBS Browser Source page
│   │   ├── overlay.js        # receives WS events, renders GIFs, plays audio
│   │   └── overlay.css       # transparent background, positioning, animations
│   ├── media/
│   │   ├── validator.py      # GIF URL validation + sounds directory index
│   │   └── queue.py          # unified FIFO queue with cooldown
│   └── utils/
│       └── config.py         # loads .env and config.yaml into typed settings
└── tests/
    ├── test_validator.py
    └── test_queue.py
```

---

## How It Works

### GIF redeem flow

1. Viewer redeems the GIF reward on Twitch with a Giphy CDN URL as input.
2. Visema validates the URL against allowed domains (`i.giphy.com`, `media*.giphy.com`).
3. Valid → enqueued in the media queue. Invalid → redemption cancelled, points refunded.
4. Queue worker broadcasts the GIF payload to all connected OBS overlays via WebSocket.
5. Overlay renders the GIF, holds for `display_duration_seconds`, then fades out.
6. After `cooldown_seconds`, the next queued item is processed.

### Sound redeem flow

1. Viewer redeems the sound reward with a sound name as input (e.g. `"boom"`).
2. Visema normalises the input and looks it up in the sounds index.
3. Found → enqueued. Not found → redemption cancelled, points refunded.
4. Queue worker broadcasts the audio payload to OBS overlays.
5. Overlay plays the sound through the Web Audio API at configured volume.
6. On `ended` event, the overlay sends an ack back so the queue starts its cooldown.

---

## Extending

- **Skip command** — add a `!visemaskip` chat command (moderator only) that advances the queue.
- **Per-user cooldown** — track last redemption time per viewer to prevent spam.
- **Blocklist** — add a `blocked_users` list in `config.yaml`; redemptions are auto-cancelled.
- **Hot-reload sounds** — watch `sounds/` for file changes and rebuild the index at runtime.

---

## License

[MIT](LICENSE)
