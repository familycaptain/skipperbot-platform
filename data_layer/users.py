"""Data Layer — Users
====================
CRUD and authentication for the unified user identity table.

Canonical user_id is the lowercase person name (e.g. "alice").
Passwords are hashed with bcrypt. Discord IDs are stored for channel linking.
"""

import bcrypt
from collections.abc import Iterable, Mapping

from data_layer.db import fetch_one, fetch_all, execute, execute_returning


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def parse_roles(user_or_role) -> list[str]:
    """Normalize a user row or role value into a unique, ordered role list."""
    role_value = user_or_role
    if isinstance(user_or_role, Mapping):
        role_value = user_or_role.get("role") or user_or_role.get("roles")

    raw_parts: list[str] = []
    if isinstance(role_value, str):
        raw_parts = role_value.split(",")
    elif isinstance(role_value, Iterable) and not isinstance(role_value, (str, bytes, bytearray)):
        for item in role_value:
            raw_parts.extend(parse_roles(item))
    elif role_value:
        raw_parts = [str(role_value)]

    seen: set[str] = set()
    roles: list[str] = []
    for part in raw_parts:
        role = str(part).strip().lower()
        if role and role not in seen:
            seen.add(role)
            roles.append(role)
    return roles


def has_role(user_or_role, role: str) -> bool:
    """Return True when the user/role value includes the requested role."""
    target = role.strip().lower()
    return bool(target) and target in parse_roles(user_or_role)


def has_any_role(user_or_role, *roles: str) -> bool:
    """Return True when the user/role value includes any requested role."""
    parsed = set(parse_roles(user_or_role))
    return any(role.strip().lower() in parsed for role in roles if role and role.strip())


def get_users_with_any_role(*roles: str) -> list[dict]:
    """Return all users who have any of the requested roles."""
    if not roles:
        return []
    return [user for user in get_all_users() if has_any_role(user, *roles)]


def get_users_without_any_role(*roles: str) -> list[dict]:
    """Return all users who do not have any of the requested roles."""
    if not roles:
        return get_all_users()
    return [user for user in get_all_users() if not has_any_role(user, *roles)]


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_user(name: str) -> dict | None:
    """Get a user by canonical name (primary key)."""
    return fetch_one("SELECT * FROM users WHERE name = %s", (name.lower().strip(),))


def display_name_for(name: str) -> str:
    """Human display name used to ADDRESS/refer to a user in PROSE (greetings,
    DMs, sentences, spoken output). The account ``name`` (username) stays the
    tool-target identifier and is NEVER the spoken/written address.

    Falls back to the title-cased username only when ``display_name`` is
    missing/blank (it is NOT NULL and defaulted to ``name.capitalize()`` at
    install; this is a guard so the address is never blank).

    INPUT HYGIENE: ``display_name`` is freeform, user-controlled text now injected
    into the authoritative system/dynamic-context layer, so collapse any
    whitespace/newlines and cap the length — a display name can't inject prompt
    structure or spill across lines.
    """
    dn = ""
    if name:
        u = get_user(name)
        dn = ((u or {}).get("display_name") or "").strip()
    if not dn:
        dn = (name or "").strip().capitalize()
    dn = " ".join(dn.split())[:64]
    return dn or (name or "").strip().capitalize()


def get_user_by_discord_id(discord_id: str) -> dict | None:
    """Get a user by their Discord numeric ID."""
    return fetch_one("SELECT * FROM users WHERE discord_id = %s", (str(discord_id),))


def get_all_users() -> list[dict]:
    """Get all users."""
    return fetch_all("SELECT * FROM users ORDER BY name")


def get_primary_user() -> str:
    """The primary user — the person who installed/owns this Skipper.

    Used so onboarding, the PM, and chat know WHO to engage (e.g. the onboarding
    goal is about this person). Resolution order:
      1. The explicit ``primary`` role (authoritative — a human assigned it).
      2. The stored reference (app_config scope=platform, key=primary_user).
      3. The earliest-created non-bot user (the installer), which is then cached.
    Returns "" if no human user exists yet.
    """
    # 1. Explicit 'primary' role wins.
    row = fetch_one(
        "SELECT name FROM users WHERE position('primary' in lower(role)) > 0 "
        "ORDER BY created_at, name LIMIT 1"
    )
    if row and row.get("name"):
        return row["name"]

    # 2. Stored reference.
    try:
        from app_platform import config as _pc
        stored = _pc.get("primary_user", scope="platform")
        if stored:
            return str(stored)
    except Exception:
        pass

    # 3. Fallback: earliest non-bot user; cache it so it's stable.
    row = fetch_one(
        "SELECT name FROM users WHERE position('bot' in lower(role)) = 0 "
        "ORDER BY created_at, name LIMIT 1"
    )
    name = row["name"] if row else ""
    if name:
        try:
            from app_platform import config as _pc
            _pc.set("primary_user", name, scope="platform", by="system")
        except Exception:
            pass
    return name


def get_human_users() -> list[dict]:
    """Get only human users (excludes bots). Use for UI pickers/dropdowns."""
    return [user for user in get_all_users() if not has_role(user, "bot")]


def get_discord_users() -> dict[str, str]:
    """Get a mapping of discord_id → canonical name for all users with a Discord ID.

    Returns:
        Dict like {"123456789": "alice", "987654321": "bob"}
    """
    rows = fetch_all("SELECT discord_id, name FROM users WHERE discord_id IS NOT NULL")
    return {row["discord_id"]: row["name"] for row in rows}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def authenticate(name: str, password: str) -> dict | None:
    """Authenticate a user by name + password.

    Returns:
        The user dict if credentials are valid, None otherwise.
    """
    user = get_user(name)
    if not user or not user.get("password_hash"):
        return None
    if _verify_password(password, user["password_hash"]):
        return user
    return None


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def create_user(
    name: str,
    display_name: str,
    password: str | None = None,
    discord_id: str | None = None,
    role: str = "member",
) -> dict | None:
    """Create a new user.

    Args:
        name: Canonical user_id (will be lowercased).
        display_name: Human-readable name.
        password: Plaintext password (will be hashed). None = no web login.
        discord_id: Discord numeric user ID. None = no Discord linking.
        role: Role string stored in users.role. Helpers support both a
            single role ("admin") and comma-delimited roles
            ("member,parent").

    Returns:
        The created user dict, or None on conflict.
    """
    pw_hash = _hash_password(password) if password else None
    return execute_returning(
        """INSERT INTO users (name, display_name, password_hash, discord_id, role)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (name) DO NOTHING
           RETURNING *""",
        (name.lower().strip(), display_name, pw_hash, discord_id, role),
    )


def update_password(name: str, new_password: str) -> bool:
    """Update a user's password.

    Returns:
        True if the user was found and updated.
    """
    pw_hash = _hash_password(new_password)
    rows = execute(
        "UPDATE users SET password_hash = %s, updated_at = now() WHERE name = %s",
        (pw_hash, name.lower().strip()),
    )
    return rows > 0


def update_discord_id(name: str, discord_id: str | None) -> bool:
    """Link or unlink a Discord ID for a user.

    Returns:
        True if the user was found and updated.
    """
    rows = execute(
        "UPDATE users SET discord_id = %s, updated_at = now() WHERE name = %s",
        (discord_id, name.lower().strip()),
    )
    return rows > 0


def update_role(name: str, role: str) -> bool:
    """Update a user's role.

    Returns:
        True if the user was found and updated.
    """
    rows = execute(
        "UPDATE users SET role = %s, updated_at = now() WHERE name = %s",
        (role, name.lower().strip()),
    )
    return rows > 0


def delete_user(name: str) -> bool:
    """Delete a user.

    Returns:
        True if the user was found and deleted.
    """
    rows = execute("DELETE FROM users WHERE name = %s", (name.lower().strip(),))
    return rows > 0
