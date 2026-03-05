"""Bot configuration."""

import os

# Telegram
BOT_TOKEN = os.environ["OLMO_BOT_TOKEN"]

# Allowed Telegram user IDs (comma-separated)
ALLOWED_USERS = {
    int(uid.strip())
    for uid in os.environ.get("OLMO_ALLOWED_USERS", "").split(",")
    if uid.strip()
}

# Web2API base URL
WEB2API_URL = os.environ.get("OLMO_WEB2API_URL", "http://127.0.0.1:8010")

# Models mapped to web2api endpoints
MODELS = {
    "olmo-32b": "/allenai/olmo-32b",
    "olmo-32b-think": "/allenai/olmo-32b-think",
    "olmo-7b": "/allenai/olmo-7b",
    "tulu-8b": "/allenai/tulu-8b",
    "tulu-70b": "/allenai/tulu-70b",
}

DEFAULT_MODEL = "olmo-32b"

# Request timeout (scraping can be slow)
REQUEST_TIMEOUT = 120
