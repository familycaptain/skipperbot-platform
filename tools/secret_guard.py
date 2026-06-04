"""Shared guard: keep credential/secret files unreadable by the file tools.

The sandboxed file-read tools (cat_file / tail_file / grep_search / os_level_find
/ ls_dir) operate within the app root — which is exactly where ``.env`` lives (the
master ``SKIPPERBOT_SECRET_KEY`` plus the DB and OpenAI credentials). Without this
guard a single prompt-injected turn could ``cat_file('.env')`` or
``grep_search('KEY', '.env')`` and dump every secret in one call.

This denylist refuses secret-bearing files by name, independent of the path
sandbox, and resolves symlinks so an in-sandbox link pointing at a secret is
caught too. (Security audit finding #5.)
"""

import os

# Exact dotfile / credential basenames.
_SECRET_EXACT = {
    ".env", ".pgpass", ".netrc",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}
# Suffixes that mark private keys / certs / credential stores.
_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".pgpass", ".kdbx", ".keystore")
# Directory names that should never be traversed or read.
_SECRET_DIRS = {".git", ".ssh"}


def is_secret_name(name: str) -> bool:
    """Basename-only secret check (fast path for directory walks)."""
    b = (name or "").lower()
    if b in _SECRET_EXACT:
        return True
    if b.startswith(".env"):                       # .env, .env.local, .env.prod, ...
        return True
    if b.endswith(_SECRET_SUFFIXES):
        return True
    if "service-account" in b and b.endswith(".json"):
        return True
    return False


def is_secret_path(path: str) -> bool:
    """True if ``path`` (after resolving symlinks) is a secret file or lives
    under a secret directory (``.git`` / ``.ssh``)."""
    try:
        real = os.path.realpath(path)
    except Exception:
        real = path or ""
    if is_secret_name(os.path.basename(real)):
        return True
    parts = {p.lower() for p in real.split(os.sep) if p}
    return bool(parts & _SECRET_DIRS)


def deny_if_secret(path: str) -> str | None:
    """Return an error string if ``path`` is a protected secret file, else None."""
    if is_secret_path(path):
        return "Error: reading secret/credential files (.env, keys, etc.) is not permitted."
    return None
