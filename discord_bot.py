"""
SkipperBot Discord Integration
Connects to Discord, routes messages through the chat engine, and handles DM relay.
"""

import os
import asyncio
import discord
from dotenv import load_dotenv

import re
from config import logger, SHOW_ENTITY_IDS
from chat import process_chat
from discord_config import is_allowed_channel
from data_layer.users import get_user_by_discord_id, get_discord_users

load_dotenv()


def _discord_token() -> str:
    """The Discord bot token, from the Settings Integrations panel (encrypted,
    scope=platform). App settings are authoritative — no .env fallback."""
    from app_platform import settings as _settings
    return _settings.get("discord_token", scope="platform", secret=True, default="") or ""

# Signalled when the bot is fully connected and ready to receive messages
_ready_event = asyncio.Event()

# File extensions we can safely read as text and inject into the message
TEXT_EXTENSIONS = {
    ".txt", ".json", ".py", ".csv", ".md", ".yaml", ".yml",
    ".log", ".xml", ".html", ".css", ".js", ".ts", ".toml",
    ".ini", ".cfg", ".conf", ".sh", ".bash", ".env", ".sql",
    ".jsonl", ".tsv", ".rst", ".tex",
}

# Max bytes to read per attachment (avoid blowing up context)
MAX_ATTACHMENT_BYTES = 50_000  # ~50 KB

# Entity ID prefixes used across the system (order matters: longer prefixes first)
_ID_PREFIXES = r"(?:lnk|li|g|p|t|r|j|n|l|d|a|m|k|c)"
_ID_HEX = r"[a-f0-9]{6,8}"

# Patterns for entity IDs in various wrapper formats
_ENTITY_ID_PATTERNS = [
    # (ID: p-abc12345) or (p-abc12345)
    re.compile(rf"\s*\((?:ID:\s*)?{_ID_PREFIXES}-{_ID_HEX}\)", re.IGNORECASE),
    # [p-abc12345]
    re.compile(rf"\s*\[{_ID_PREFIXES}-{_ID_HEX}\]", re.IGNORECASE),
    # **r-abc12345** — title  (bold-wrapped ID with optional em dash)
    re.compile(rf"\*\*{_ID_PREFIXES}-{_ID_HEX}\*\*\s*[—–\-]*\s*", re.IGNORECASE),
    # **ID:** p-abc12345  (markdown bold label)
    re.compile(rf"\*\*ID:\*\*\s*{_ID_PREFIXES}-{_ID_HEX}", re.IGNORECASE),
    # ID: p-abc12345  (plain label)
    re.compile(rf"\bID:\s*{_ID_PREFIXES}-{_ID_HEX}", re.IGNORECASE),
    # Standalone entity ID (with optional trailing em dash/colon/space)
    re.compile(rf"\b{_ID_PREFIXES}-{_ID_HEX}\b:?\s*[—–]*\s?", re.IGNORECASE),
]


def strip_entity_ids(text: str) -> str:
    """Remove entity IDs (g-*, p-*, t-*, etc.) from text for cleaner user output.

    Applied in order: wrapped formats first, then standalone IDs.
    The original text with IDs is preserved in chat history for AI context.
    """
    if SHOW_ENTITY_IDS:
        return text
    for pattern in _ENTITY_ID_PATTERNS:
        text = pattern.sub("", text)
    # Clean up artifacts: double spaces, empty parens/brackets, empty bold, orphaned em dashes
    text = re.sub(r"  +", " ", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"\*\*\s*\*\*", "", text)  # empty bold markers
    text = re.sub(r"^\s*[—–]\s*", "", text, flags=re.MULTILINE)  # orphaned leading em dash
    # Clean up lines that became empty or have trailing whitespace
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines)


intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guild_messages = True

client = discord.Client(intents=intents)


async def _trigger_typing(channel):
    """Send a typing indicator that works for all channel types."""
    try:
        await channel._state.http.send_typing(channel.id)
    except Exception:
        pass


# Cached discord_id → canonical name mapping (loaded at bot ready, refreshable)
_discord_user_cache: dict[str, str] = {}


def _refresh_user_cache():
    """Reload the discord_id → canonical name mapping from Postgres."""
    global _discord_user_cache
    _discord_user_cache = get_discord_users()
    logger.info("DISCORD: User cache loaded — %d users", len(_discord_user_cache))


@client.event
async def on_ready():
    logger.info("DISCORD: Logged in as %s (id: %s)", client.user, client.user.id)
    logger.info("DISCORD: Connected to %d guilds", len(client.guilds))
    await asyncio.to_thread(_refresh_user_cache)
    _ready_event.set()


@client.event
async def on_message(message: discord.Message):
    # Never respond to ourselves or other bots
    if message.author == client.user:
        return
    if message.author.bot:
        return

    author_id = str(message.author.id)

    # Resolve person name from Discord ID (Postgres-backed, cached)
    person_name = _discord_user_cache.get(author_id)
    if not person_name:
        # Cache miss — try a direct DB lookup (new user added since last cache load)
        db_user = await asyncio.to_thread(get_user_by_discord_id, author_id)
        if db_user:
            person_name = db_user["name"]
            _discord_user_cache[author_id] = person_name
        else:
            logger.debug("DISCORD: Ignoring message from unknown user %s (%s)", message.author, author_id)
            return

    # Determine if this is a DM or a guild channel message
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_allowed_ch = is_allowed_channel(message.channel.id) if not is_dm else False

    if not is_dm and not is_allowed_ch:
        # Not a DM and not in an allowed channel — ignore
        return

    user_message = message.content.strip()

    # Handle attachments
    attachment_text = await _read_attachments(message.attachments)
    if attachment_text:
        if user_message:
            user_message += "\n\n" + attachment_text
        else:
            user_message = attachment_text

    if not user_message:
        return

    logger.info("DISCORD: Message from %s (%s): %s", person_name, "DM" if is_dm else f"#{message.channel.name}", user_message[:100])

    import time as _time
    last_msg_time = _time.monotonic()

    # Progress callback: sends mid-turn messages and re-triggers typing
    async def _send_progress(text: str):
        nonlocal last_msg_time
        for chunk in _split_message(text):
            await message.channel.send(chunk)
        last_msg_time = _time.monotonic()
        # Sending a message kills the typing indicator; re-trigger immediately
        # so there's no gap before the context manager's next 5s refresh
        await _trigger_typing(message.channel)

    # Keepalive: send follow-up messages during long silences (runs alongside typing)
    done_event = asyncio.Event()

    async def _keepalive():
        from chat import KEEPALIVE_MESSAGES
        import random
        idx = 0
        while not done_event.is_set():
            try:
                await asyncio.wait_for(done_event.wait(), timeout=5)
                break
            except asyncio.TimeoutError:
                pass
            elapsed = _time.monotonic() - last_msg_time
            if elapsed >= 15 and idx < len(KEEPALIVE_MESSAGES):
                try:
                    await message.channel.send(random.choice(KEEPALIVE_MESSAGES))
                    last_msg_time = _time.monotonic()
                    idx += 1
                except Exception:
                    pass

    # typing() context manager auto-refreshes every 5s.
    # asyncio.to_thread() in process_chat keeps the event loop free so refreshes work.
    keepalive_task = asyncio.create_task(_keepalive())
    try:
        async with message.channel.typing():
            try:
                response = await process_chat(person_name, user_message, send_progress=_send_progress)
            except Exception as e:
                logger.error("DISCORD: Error processing message from %s: %s", person_name, str(e))
                response = "Sorry, I ran into an error processing that. Please try again."
        # typing() context exits here — indicator stops before we send the response
        done_event.set()
        if response:
            for chunk in _split_message(response):
                await message.channel.send(chunk)
    finally:
        done_event.set()
        keepalive_task.cancel()


async def _read_attachments(attachments: list[discord.Attachment]) -> str:
    """Read text-safe attachments and return their content as a formatted string.

    Text files are downloaded and included inline. Binary/unsupported files
    are noted but not read. Large files are truncated.
    """
    if not attachments:
        return ""

    parts = []
    for att in attachments:
        ext = os.path.splitext(att.filename)[1].lower()

        if ext not in TEXT_EXTENSIONS:
            parts.append(f"[Attached file: {att.filename} ({att.size:,} bytes) — binary/unsupported format, not read]")
            continue

        if att.size > MAX_ATTACHMENT_BYTES:
            parts.append(f"[Attached file: {att.filename} ({att.size:,} bytes) — too large to read, limit is {MAX_ATTACHMENT_BYTES:,} bytes]")
            continue

        try:
            raw = await att.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                parts.append(f"[Attached file: {att.filename} — could not decode as UTF-8]")
                continue

            parts.append(f"--- Attached file: {att.filename} ---\n{text.rstrip()}\n--- End of {att.filename} ---")
            logger.info("DISCORD: Read attachment %s (%d bytes)", att.filename, len(raw))
        except Exception as e:
            logger.error("DISCORD: Failed to read attachment %s: %s", att.filename, str(e))
            parts.append(f"[Attached file: {att.filename} — failed to download: {str(e)}]")

    return "\n\n".join(parts)


def _split_message(text: str, max_len: int = 2000) -> list[str]:
    """Split a long message into Discord-safe chunks."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at a newline
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            # No newline found, split at max_len
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def send_dm(person_name: str, message_text: str) -> str:
    """Send a Discord DM to a family member by name. Returns status string."""
    from config import discord_enabled
    if not discord_enabled():
        return "Discord is disabled (DISCORD_ENABLED=false). Message not sent."
    # Reverse lookup: name → discord_id from cache
    discord_id = None
    for did, name in _discord_user_cache.items():
        if name == person_name.lower().strip():
            discord_id = did
            break
    if not discord_id:
        # Try DB directly in case cache is stale
        from data_layer.users import get_user
        db_user = await asyncio.to_thread(get_user, person_name)
        discord_id = db_user.get("discord_id") if db_user else None
    if not discord_id:
        valid = ", ".join(sorted(set(_discord_user_cache.values())))
        return f"Error: No Discord ID found for '{person_name}'. Valid names: {valid}"

    try:
        user = await client.fetch_user(int(discord_id))
        if not user:
            return f"Error: Could not find Discord user for '{person_name}' (ID: {discord_id})"

        dm_channel = await user.create_dm()
        for chunk in _split_message(message_text):
            await dm_channel.send(chunk)

        logger.info("DISCORD: Sent DM to %s: %s", person_name, message_text[:100])
        return f"DM sent to {person_name} successfully."
    except discord.Forbidden:
        return f"Error: Cannot send DM to {person_name} — they may have DMs disabled."
    except Exception as e:
        return f"Error sending DM to {person_name}: {str(e)}"


async def wait_until_ready():
    """Block until the Discord bot is fully connected and joined guilds."""
    if not _discord_token():
        return  # no bot to wait for
    await _ready_event.wait()


async def start_discord_bot():
    """Start the Discord bot. Runs forever as an async task."""
    token = _discord_token()
    if not token:
        logger.warning("DISCORD: No token configured — Discord bot disabled.")
        _ready_event.set()  # unblock waiters even if bot is disabled
        return

    logger.info("DISCORD: Starting bot...")
    try:
        await client.start(token)
    except Exception as e:
        logger.error("DISCORD: Bot failed to start: %s", str(e))


async def stop_discord_bot():
    """Gracefully shut down the Discord bot."""
    if client and not client.is_closed():
        await client.close()
        logger.info("DISCORD: Bot stopped.")
