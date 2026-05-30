"""Secret encryption at rest (AES-256-GCM).

Used to protect secret-flagged settings (API keys, tokens) that live in the
``public.app_config`` table. The encryption key is ``SKIPPERBOT_SECRET_KEY``
in ``.env`` — it never enters the database, so a leaked DB backup yields only
ciphertext.

Design:
  - AES-256-GCM (authenticated encryption) via ``cryptography``.
  - A fresh random 96-bit nonce per value (never reused).
  - Versioned, self-describing token: ``enc:1:<base64url(nonce || ct||tag)>``.
    The version prefix lets us evolve the scheme later; values WITHOUT the
    prefix are treated as plaintext (so non-secret values and any
    pre-migration plaintext pass straight through ``decrypt``).

Key handling (``SKIPPERBOT_SECRET_KEY``):
  - If it is a urlsafe-base64 string that decodes to exactly 32 bytes (what
    ``generate_key`` emits), it is used directly as the AES-256 key.
  - Otherwise it is treated as a passphrase and hashed to 32 bytes with
    SHA-256. This is forgiving (any string works) but weaker against a brute
    force of a low-entropy passphrase — operators should use ``generate_key``.

Failure behavior is deliberately loud, never silent:
  - ``encrypt`` with no key  -> SecretKeyMissing  (caller must surface
    "set SKIPPERBOT_SECRET_KEY before saving secrets").
  - ``decrypt`` of an encrypted value with no key -> SecretKeyMissing.
  - ``decrypt`` with the wrong/changed key or corrupt data -> SecretDecryptError
    (so a rotated key surfaces a clear error instead of garbage).

Generate a key:
    python -m app_platform.secrets
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Token format version. Bump if the scheme changes; keep old decoders if so.
_PREFIX = "enc:1:"
_NONCE_BYTES = 12  # 96-bit, the AES-GCM standard nonce size


class SecretError(Exception):
    """Base class for secret encryption/decryption failures."""


class SecretKeyMissing(SecretError):
    """SKIPPERBOT_SECRET_KEY is not set but a secret operation was attempted."""


class SecretDecryptError(SecretError):
    """A value could not be decrypted (wrong/rotated key, or corrupt data)."""


def _key() -> bytes | None:
    """Return the 32-byte AES key, or None if SKIPPERBOT_SECRET_KEY is unset."""
    raw = os.getenv("SKIPPERBOT_SECRET_KEY", "").strip()
    if not raw:
        return None
    # Preferred: an exact 32-byte urlsafe-base64 key (what generate_key emits).
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    # Fallback: derive deterministically from an arbitrary passphrase.
    return hashlib.sha256(raw.encode("utf-8")).digest()


def secret_key_available() -> bool:
    """True if SKIPPERBOT_SECRET_KEY is set (so secrets can be saved/read)."""
    return _key() is not None


def generate_key() -> str:
    """Return a fresh, cryptographically random key suitable for
    SKIPPERBOT_SECRET_KEY (urlsafe-base64 of 32 bytes)."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def is_encrypted(value: object) -> bool:
    """True if *value* is one of our ciphertext tokens."""
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* into a versioned token. Requires SKIPPERBOT_SECRET_KEY."""
    key = _key()
    if key is None:
        raise SecretKeyMissing(
            "SKIPPERBOT_SECRET_KEY is not set — cannot store an encrypted secret. "
            "Generate one with `python -m app_platform.secrets` and add it to .env."
        )
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token from :func:`encrypt`.

    A value that is not one of our tokens is returned unchanged (plaintext
    passthrough — supports non-secret values and pre-migration data).
    """
    if not is_encrypted(token):
        return token
    key = _key()
    if key is None:
        raise SecretKeyMissing(
            "SKIPPERBOT_SECRET_KEY is not set — cannot decrypt a stored secret."
        )
    try:
        blob = base64.urlsafe_b64decode(token[len(_PREFIX):])
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
    except Exception as exc:  # InvalidTag, malformed base64, short blob, ...
        raise SecretDecryptError(
            "Could not decrypt a stored secret — SKIPPERBOT_SECRET_KEY may have "
            "changed since it was saved, or the value is corrupt."
        ) from exc


def ensure_secret_key(env_path=None) -> str:
    """Make sure SKIPPERBOT_SECRET_KEY exists; self-provision it if not.

    Called once at startup (from scripts/init_db.py, which both the Docker
    entrypoint and the native start script run before the agent). So a
    first-time user never has to generate a key by hand — but the explicit
    ``.env`` slot still wins if they set one (or carry one across machines).

    Behavior:
      - Key already set (env or .env): no-op, returns "present".
      - Not set: generate one, set it in this process's environment, and
        persist it to ``.env`` (replacing a blank ``SKIPPERBOT_SECRET_KEY=``
        line, or appending one, or creating ``.env``). Returns "generated".
      - Generated but the file couldn't be written: returns "unpersisted"
        (the key works for this run but would regenerate next boot — the
        caller should warn).

    The key is deliberately stored in ``.env`` (outside the database) so a
    leaked DB backup can't decrypt anything.
    """
    if os.getenv("SKIPPERBOT_SECRET_KEY", "").strip():
        return "present"

    key = generate_key()
    os.environ["SKIPPERBOT_SECRET_KEY"] = key  # usable immediately this run

    import pathlib
    path = pathlib.Path(env_path) if env_path else pathlib.Path(".env")
    line = f"SKIPPERBOT_SECRET_KEY={key}\n"
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines(keepends=True)
            for i, ln in enumerate(lines):
                if ln.lstrip().startswith("SKIPPERBOT_SECRET_KEY="):
                    lines[i] = line          # fill in a blank/placeholder slot
                    break
            else:
                if lines and not lines[-1].endswith("\n"):
                    lines[-1] += "\n"
                lines.append(line)
            path.write_text("".join(lines), encoding="utf-8")
        else:
            path.write_text(line, encoding="utf-8")
        return "generated"
    except OSError:
        return "unpersisted"


if __name__ == "__main__":
    # Convenience: print a fresh key for the operator to paste into .env.
    print(generate_key())
