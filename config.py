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

# Web2API base URL and access token
WEB2API_URL = os.environ.get("OLMO_WEB2API_URL", "http://127.0.0.1:8010")
WEB2API_TOKEN = os.environ.get("OLMO_WEB2API_TOKEN", "")

# Models mapped to web2api endpoints
MODELS = {
    "olmo-32b": "/allenai/olmo-32b",
    "olmo-32b-think": "/allenai/olmo-32b-think",
    "olmo-7b": "/allenai/olmo-7b",
    "tulu-8b": "/allenai/tulu-8b",
    "tulu-70b": "/allenai/tulu-70b",
    "molmo2": "/allenai/molmo2",
    "molmo2-track": "/allenai/molmo2-track",
}

# Models that support image/video input
VISION_MODELS = {"molmo2", "molmo2-track"}

# Models that support tool calling (web search)
TOOL_MODELS = {"olmo-32b", "olmo-7b"}

DEFAULT_MODEL = "olmo-32b"

# Default MCP tools URL passed to models (scraped inside Docker container)
# Uses container-internal port 8000, filtered to brave-search only
DEFAULT_TOOLS_URL = os.environ.get(
    "OLMO_TOOLS_URL", "http://127.0.0.1:8000/mcp/only/brave-search,web-reader"
)

# Request timeout (scraping can be slow)
REQUEST_TIMEOUT = 120
