# OLMo Telegram Bot

A Telegram bot that interfaces with [Allen AI](https://playground.allenai.org/) language models (OLMo, Tülu) via [Web2API](https://github.com/Endogen/web2api).

## Features

- **Multiple models** — OLMo 3.1 32B, OLMo 32B Think (reasoning), OLMo 7B, Tülu 8B, Tülu 70B
- **Inline mode** — use `@your_bot query` in any chat
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
| `/models` | List available models |
| `/memory` | Toggle conversation memory |
| `/memory enable` | Enable memory |
| `/memory disable` | Disable memory |
| `/clear` | Clear conversation history |
| `/status` | Show current settings |

Any regular message is sent to the currently selected model.

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

### Run

```bash
python bot.py
```

### Inline Mode

To enable inline mode, tell [@BotFather](https://t.me/BotFather):

1. `/setinline`
2. Select your bot
3. Set a placeholder like `Ask OLMo...`

Then type `@your_bot your question` in any Telegram chat.

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
