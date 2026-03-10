# OLMo Telegram Bot

A Telegram bot that interfaces with [Allen AI](https://playground.allenai.org/) language and vision models via [Web2API](https://github.com/Endogen/web2api).

## Features

- **Multiple models** — OLMo 3.1 32B, OLMo 32B Think (reasoning), OLMo 7B, Tülu 8B, Tülu 70B
- **Vision** — Molmo 2 8B for image and video understanding
- **Point overlay** — ask Molmo 2 to point at objects and get an annotated image back with colored markers
- **Web search** — all text models can search the web via Brave Search when they need current info
- **Auto-switch** — sending a photo or video automatically switches to Molmo 2 if the current model doesn't support vision
- **Conversation memory** — optional per-user chat history (off by default)
- **Access control** — restrict to specific Telegram user IDs

## Commands

| Command | Description |
|---|---|
| `/start` | Show help and current settings |
| `/olmo32b` | Switch to OLMo 3.1 32B Instruct (default) |
| `/think` | Switch to OLMo 32B Think (reasoning) |
| `/olmo7b` | Switch to OLMo 3 7B Instruct |
| `/tulu8b` | Switch to Tülu 3 8B |
| `/tulu70b` | Switch to Tülu 3 70B |
| `/molmo2` | Switch to Molmo 2 8B (vision: images & video) |
| `/molmo2track` | Switch to Molmo 2 8B 8fps tracking |
| `/search <query>` | Web search via Brave Search (uses a tool-capable model) |
| `/models` | List available models |
| `/memory` | Toggle conversation memory |
| `/clear` | Clear conversation history |
| `/status` | Show current settings |

Any regular message is sent to the currently selected model.

## Vision (Molmo 2)

Send a **photo or video with a caption** and the bot will analyze it using Molmo 2:

- The caption is used as the prompt (e.g. "What's in this image?")
- If no caption is provided, it defaults to "Describe this image in detail."
- If the current model doesn't support vision, the bot **automatically switches to Molmo 2** for that message
- Supports photos, videos, and image/video file attachments

### Point Overlay

Ask Molmo 2 to **point at objects** and the bot draws colored markers on the original image:

- **"Point to the eyes"** → annotated image with numbered red/blue dots on each eye
- **"Find the cat"** → single marker on the detected object
- **"Show me where the people are"** → multiple numbered markers

Markers are smooth and anti-aliased (4× supersampled with LANCZOS downscaling), auto-scaled to image size, with white borders and numbered labels for multiple points.

Prompts that trigger pointing: `Point to...`, `Find the...`, `Where is the...`, `Show me where...`, `Locate the...`

## Web Search

Use `/search <query>` to search the web via [Brave Search](https://search.brave.com/) and the [Web2API MCP bridge](https://github.com/Endogen/web2api#mcp-tools). Only models that support Allen AI's native tool calling (`olmo-32b`, `olmo-7b`) can use search — if the current model doesn't support it, the bot automatically switches to `olmo-32b` for that query.

Configure the tool bridge URL via the `OLMO_TOOLS_URL` environment variable.

## Setup

### Prerequisites

- Python 3.10+
- A running [Web2API](https://github.com/Endogen/web2api) instance with the `allenai` recipe installed
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Install

```bash
git clone https://github.com/Endogen/olmo-bot.git
cd olmo-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your values
```

| Variable | Required | Description |
|---|---|---|
| `OLMO_BOT_TOKEN` | Yes | Telegram bot token |
| `OLMO_ALLOWED_USERS` | No | Comma-separated Telegram user IDs (empty = allow all) |
| `OLMO_WEB2API_URL` | No | Web2API URL (default: `http://127.0.0.1:8010`) |
| `OLMO_TOOLS_URL` | No | MCP bridge URL for web search (default: container-internal brave-search endpoint) |

### Run

```bash
python bot.py
```

### Systemd Service (Optional)

```ini
[Unit]
Description=OLMo Telegram Bot
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/olmo-bot
EnvironmentFile=/path/to/olmo-bot/.env
ExecStart=/path/to/olmo-bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## License

MIT
