# Visema

![Visema](docs/img.png "Visema — Twitch Channel Points Bot")

A local Twitch bot that lets viewers spend Channel Points to display a GIF or play an audio clip on stream via an OBS Browser Source overlay.

Visema listens for Channel Points redemptions through Twitch EventSub, validates the request (GIF URL against Giphy CDN domains, or sound name against a local `sounds/` index), enqueues it in a FIFO queue, and broadcasts the payload to the OBS overlay via WebSocket. The overlay renders GIFs with fade-in/out animations and plays audio clips with completion acknowledgment back to the queue worker.

**No external API keys required** — GIF validation uses only URL domain checking against Giphy's CDN, and audio is entirely local.

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — for dependency management and virtual environment creation
- **OBS Studio** — for the Browser Source overlay
- **A Twitch developer app** (see below)
- **Two Twitch accounts**: a broadcaster account (your streaming channel) and a bot account (for sending chat messages)

## Quick Start

### 1. Install uv

Follow the official installation guide: https://docs.astral.sh/uv/getting-started/installation/

On Linux/macOS (one-liner):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Clone and set up the project

```bash
git clone https://github.com/dilidin2/visema.git
cd visema
```

### 3. Create the virtual environment and install dependencies

```bash
uv venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

uv pip install -r requirements.txt
```

### 4. Get Twitch API Credentials

1. Go to https://dev.twitch.tv/console
2. Click **"Register Your Application"**
3. Fill in:
   - **Name**: any name for your app
   - **OAuth Redirect URLs**: `http://localhost:17563`
   - **Category**: `Chat Bot`
   - **Client Type**: `Confidential`
4. Copy the **Client ID**
5. Click **"New Secret"** under Client Secret, then copy it

### 5. Configure `.env`

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and paste your Client ID and Client Secret:

```env
TWITCH_CLIENT_ID=your_client_id_here
TWITCH_CLIENT_SECRET=your_client_secret_here
```

Leave the OAuth token fields empty — they are populated automatically on first run.

### 6. Configure `config.yaml`

Copy the example file and customize it:

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` and set:

- **`twitch.target_channel`**: your broadcaster's Twitch username (where redemptions happen)
- **`twitch.bot_channel`**: your bot account's Twitch username (sends chat messages)
- **`twitch.reward_gif`** and **`twitch.reward_sound`**: the exact names of your Channel Points rewards (must match the names in your Twitch dashboard — see step 8)

### 7. Authenticate the broadcaster account

Run the bot for the first time:

```bash
python -m visema.main --setup
```

A browser window will open asking you to authorize the app with your **broadcaster account** (the one you stream from). Log in and click **Authorize**.

After successful authorization, the broadcaster tokens are saved to `.env` automatically.

### 8. Authenticate the bot account

1. Open `.env` and **delete** the bot account tokens (the lines starting with `BOT_ACCESS_TOKEN=` and `BOT_REFRESH_TOKEN=`). This forces a fresh OAuth flow for the bot account.

2. Run the bot again:

   ```bash
   python -m visema.main --setup
   ```

3. The first browser window will open again for the broadcaster account — you're already authorized, so just click **Authorize** once more.

4. A **second** browser window will open for the **bot account**. Log in with your bot account's Twitch credentials and click **Authorize**.

5. After both authorizations complete, both sets of tokens are saved to `.env`. You now have separate broadcaster and bot accounts configured.

> **Why two accounts?** The broadcaster account is used for EventSub redemptions and API calls on your streaming channel. The bot account is used only for sending chat messages (confirmations, errors, command responses). This separation keeps the bot's activity separate from your streamer identity.

### 9. Set up Channel Points rewards

1. Go to your **Creator Dashboard** → **Channel Points** (Ricompense spettatore / Viewer Rewards)
2. Click **Manage Rewards & Redemptions** (Gestisci i potenziamenti e i punti canale)
3. Scroll to the bottom and click **Add a custom reward** (Aggiungi ricompensa personalizzata)
4. Create the **GIF** reward:
   - **Name**: must match `reward_gif` in `config.yaml` exactly (default: `"Show a GIF"`)
   - **Prompt**: something like *"Paste a direct GIF link from Giphy"*
   - **Cost**: set your desired point cost
   - **Enable**: make sure it's enabled
5. Create the **Audio** reward:
   - **Name**: must match `reward_sound` in `config.yaml` exactly (default: `"Play a Sound"`)
   - **Prompt**: something like *"Type the name of a sound to play"*
   - **Cost**: set your desired point cost
   - **Enable**: make sure it's enabled

> **Important**: The reward names in your Twitch dashboard must match the values of `reward_gif` and `reward_sound` in `config.yaml` exactly (case-sensitive). The bot resolves reward IDs from these names via the Twitch API on startup.

### 10. Add sound files

Place your audio files (MP3, OGG, or WAV) in the `sounds/` folder:

```bash
cp my_sounds/*.mp3 sounds/
```

Use lowercase filenames with underscores (e.g. `vine_boom.mp3`, `sad_trombone.mp3`). Viewers will request sounds by name — spaces in their input are automatically converted to underscores.

### 11. Add the OBS Browser Source

1. In OBS Studio, add a **Browser Source** to your scene
2. Set the URL to: `http://127.0.0.1:9876/overlay`
3. Set width/height to match your canvas (e.g. 1920 × 1080)
4. **Disable** "Shutdown source when not visible"
5. **Enable** "Refresh browser when scene becomes active" (recommended)
6. **Enable** "Allow transparency"

The overlay connects automatically to the WebSocket at `ws://127.0.0.1:9876/ws` on load.

> **Audio note**: Make sure the Browser Source audio track is **unmuted** in OBS's Audio Mixer. Audio played through the overlay routes through OBS's audio pipeline.

### 12. Start the bot

```bash
python -m visema.main
```

That's it! Viewers can now spend Channel Points to show GIFs and play sounds on your stream.

## How It Works

### GIF Flow

1. A viewer redeems the **"Show a GIF"** Channel Points reward and pastes a Giphy direct link
2. The bot validates the URL against Giphy's CDN domains (`i.giphy.com`, `media.giphy.com`, `media0-4.giphy.com`)
3. If valid, the GIF is enqueued and the redemption is fulfilled
4. If invalid (e.g. a `giphy.com` page URL instead of a direct link), the redemption is **cancelled** and points are refunded
5. The GIF is displayed on the OBS overlay with a fade-in/out animation for the configured duration
6. After the configured cooldown, the next item in the queue is processed

### Audio Flow

1. A viewer redeems the **"Play a Sound"** reward and types a sound name
2. The bot normalizes the input (lowercase, strip punctuation, spaces → underscores) and looks it up in the local `sounds/` index
3. If found, the audio is enqueued and the redemption is fulfilled
4. If not found, the redemption is **cancelled** and points are refunded
5. The audio plays through the OBS overlay
6. When playback ends, the overlay sends an acknowledgment back to the bot
7. After the configured cooldown, the next item is processed

### Unified Queue

Both GIF and audio events share a single FIFO queue with a shared maximum size and cooldown. This prevents resource contention and ensures orderly processing.

## Chat Commands

The bot listens for these commands in chat (via the bot account):

| Command | Description |
|---|---|
| `!gif` | How to find and copy a Giphy direct link |
| `!sound` | How to use the sound redeem + reminder to use `!soundlist` |
| `!soundlist` | Lists all available sound names from the `sounds/` folder |

All command responses are configurable in `config.yaml` under the `commands:` section.

## GIF Links — How to Get a Direct URL

Visema only accepts **direct CDN links** from Giphy. To get one:

1. Go to [giphy.com](https://giphy.com) and find a GIF
2. **Right-click** the GIF → **"Copy Image Address"**
3. The URL should start with `i.giphy.com` or `media.giphy.com`

> **What to reject**: URLs starting with bare `giphy.com` (no subdomain) are page URLs, not raw GIFs — the bot will reject them and tell the viewer to copy the image address instead.

## Configuration Reference

### `config.yaml`

| Key | Description |
|---|---|
| `twitch.target_channel` | Broadcaster's Twitch username |
| `twitch.target_channel_id` | Optional numeric channel ID (skips API resolution if set) |
| `twitch.bot_channel` | Bot account's Twitch username |
| `twitch.reward_gif` | Exact name of the GIF Channel Points reward |
| `twitch.reward_sound` | Exact name of the audio Channel Points reward |
| `gif.allowed_domains` | List of allowed Giphy CDN domains |
| `gif.display_duration_seconds` | How long each GIF is shown (seconds) |
| `gif.cooldown_seconds` | Wait time between items (seconds) |
| `gif.max_queue_size` | Maximum pending items in queue |
| `gif.size_percent` | GIF width as percentage of OBS canvas width |
| `audio.sounds_dir` | Path to the local audio library folder |
| `audio.allowed_extensions` | Allowed audio file formats |
| `audio.volume` | Playback volume (0.0 – 1.0) |
| `audio.cooldown_seconds` | Wait time between items (shared with GIF cooldown) |
| `audio.max_queue_size` | Maximum pending items (shared with GIF queue) |
| `overlay.port` | HTTP/WebSocket server port |
| `overlay.position` | Position on canvas: `center`, `bottom-left`, `bottom-right`, `top-left`, `top-right` |
| `commands.gif_response` | Bot's reply to `!gif` |
| `commands.sound_response` | Bot's reply to `!sound` |
| `commands.soundlist_response` | `auto` (default, generated from `sounds/`) or a hardcoded string |

### `.env`

| Variable | Description |
|---|---|
| `TWITCH_CLIENT_ID` | Your Twitch app's Client ID |
| `TWITCH_CLIENT_SECRET` | Your Twitch app's Client Secret |
| `BROADCASTER_ACCESS_TOKEN` | Auto-populated on first run |
| `BROADCASTER_REFRESH_TOKEN` | Auto-populated on first run |
| `BOT_ACCESS_TOKEN` | Auto-populated on first run |
| `BOT_REFRESH_TOKEN` | Auto-populated on first run |

## Project Structure

```
visema/
├── .env                        # secrets (never commit)
├── config.yaml                 # runtime settings
├── requirements.txt
├── sounds/                     # local audio library
│   └── (your audio files here)
├── visema/
│   ├── main.py                 # entrypoint
│   ├── twitch/
│   │   ├── auth.py             # OAuth2 flow for both accounts
│   │   ├── eventsub.py         # EventSub WebSocket listener
│   │   └── chat.py             # chat command listener
│   ├── server/
│   │   ├── app.py              # FastAPI: HTTP + WebSocket
│   │   └── ws_manager.py       # WebSocket connection manager
│   ├── overlay/
│   │   ├── index.html          # OBS Browser Source page
│   │   ├── overlay.js          # overlay logic (GIF + audio)
│   │   └── overlay.css         # overlay styles
│   ├── media/
│   │   ├── validator.py        # GIF validation + audio name resolution
│   │   └── queue.py            # unified FIFO queue
│   └── utils/
│       └── config.py           # settings loader
└── tests/
```

## Troubleshooting

- **Bot not receiving redemptions**: Make sure the reward names in `config.yaml` match your Twitch dashboard exactly (case-sensitive). Check that EventSub subscriptions are active.
- **GIFs not showing**: Ensure you're using a direct CDN link (right-click → Copy Image Address). Page URLs from `giphy.com` are rejected.
- **Audio not playing**: Check that the sound file is in the `sounds/` folder and that the Browser Source audio track is unmuted in OBS.
- **WebSocket not connecting**: Verify the overlay URL in OBS is `http://127.0.0.1:9876/overlay` and the bot is running.
- **OAuth errors**: Delete the relevant token lines from `.env` and run `python -m visema.main --setup` to re-authenticate.
