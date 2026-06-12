"""
SkipperBot Discord channel allowlist.

Which guild (server) channels Skipper responds in WITHOUT being @-mentioned.
Configured in Settings → Integrations ("Discord allowed channels"), scope=platform
— no file editing, no .env. DMs never consult this list: Skipper always answers a
known user's direct message. Sender identity is resolved from the users table
(Settings → Members, each person's ``discord_id``), not here.
"""

import re

# Cached after first read. The setting is requires_restart=True, so the value
# can't change under a running bot — caching first-read is correct, and avoids a
# settings/DB lookup on every guild message.
_allowed_cache: set[int] | None = None


def _allowed_channels() -> set[int]:
    """Allowed guild channel IDs from the Settings Integrations panel.

    Accepts a comma/space/newline-separated list of numeric channel IDs. Empty
    (the default) means Skipper replies in no shared channels — DM-only.
    """
    global _allowed_cache
    if _allowed_cache is not None:
        return _allowed_cache
    raw = ""
    try:
        from app_platform import settings as _settings
        raw = _settings.get("discord_allowed_channels", scope="platform", default="") or ""
    except Exception:
        raw = ""
    out: set[int] = set()
    for tok in re.split(r"[\s,]+", str(raw).strip()):
        if tok.isdigit():
            out.add(int(tok))
    _allowed_cache = out
    return out


def reload() -> None:
    """Drop the cached allowlist so the next check re-reads settings."""
    global _allowed_cache
    _allowed_cache = None


def is_allowed_channel(channel_id: int) -> bool:
    """True if Skipper should respond in this guild channel without a mention.

    An empty allowlist responds in no shared channels (DMs still work).
    """
    try:
        return int(channel_id) in _allowed_channels()
    except (TypeError, ValueError):
        return False
