"""
SkipperBot Discord Configuration
Identity mapping, allowlists, and channel configuration.

All identity data is loaded from data/discord_users.json (gitignored).
Copy data/discord_users.example.json to data/discord_users.json and fill
in your own Discord user IDs, guild ID, and channel IDs.
"""

import json
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "data", "discord_users.json")

def _load_config() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        return {"users": {}, "guild_id": 0, "allowed_channels": []}
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_config = _load_config()

# Discord user ID → person name mapping
DISCORD_USERS: dict[str, str] = {str(k): v for k, v in _config.get("users", {}).items()}

# Reverse lookup: person name → Discord user ID
NAME_TO_DISCORD_ID = {v: k for k, v in DISCORD_USERS.items()}

# Set of allowed Discord user IDs (DMs + guild messages)
ALLOWED_USER_IDS = set(DISCORD_USERS.keys())

# Guild configuration
GUILD_ID = int(_config.get("guild_id", 0))

# Allowed channels (no mention required)
ALLOWED_CHANNELS = {int(ch) for ch in _config.get("allowed_channels", [])}


def get_person_name(discord_user_id: str) -> str | None:
    """Look up a person's name from their Discord user ID."""
    return DISCORD_USERS.get(str(discord_user_id))


def get_discord_id(person_name: str) -> str | None:
    """Look up a Discord user ID from a person's name."""
    return NAME_TO_DISCORD_ID.get(person_name.lower().strip())


def is_allowed_user(discord_user_id: str) -> bool:
    """Check if a Discord user is in the allowlist."""
    return str(discord_user_id) in ALLOWED_USER_IDS


def is_allowed_channel(channel_id: int) -> bool:
    """Check if a channel is in the allowed list."""
    return channel_id in ALLOWED_CHANNELS
