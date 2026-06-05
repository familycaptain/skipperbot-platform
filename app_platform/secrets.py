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


# Fixed application salt for the passphrase-stretching KDF. A per-deployment
# random salt has nowhere to live (the key is the only secret), but scrypt's
# work factor still makes brute-forcing a low-entropy passphrase orders of
# magnitude costlier than the old bare SHA-256. (Audit #36.)
_KDF_SALT = b"skipperbot-secret-kdf-v1"
_KDF_N = 2 ** 14
_KDF_R = 8
_KDF_P = 1


def _decoded_32(raw: str) -> bytes | None:
    """Return raw decoded as an exact 32-byte urlsafe-b64 key, else None."""
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return None


def _key() -> bytes | None:
    """Return the 32-byte AES key used for ENCRYPTION, or None if unset.

    Preferred: an exact 32-byte urlsafe-base64 key (what generate_key emits,
    and what ensure_secret_key auto-provisions). Otherwise the value is treated
    as a passphrase and stretched with scrypt.
    """
    raw = os.getenv("SKIPPERBOT_SECRET_KEY", "").strip()
    if not raw:
        return None
    direct = _decoded_32(raw)
    if direct is not None:
        return direct
    return hashlib.scrypt(raw.encode("utf-8"), salt=_KDF_SALT,
                          n=_KDF_N, r=_KDF_R, p=_KDF_P, dklen=32,
                          maxmem=128 * _KDF_N * _KDF_R * 2)


def _decrypt_keys() -> list[bytes]:
    """Keys to try when DECRYPTING, newest first. Includes the legacy bare-SHA256
    passphrase key so values encrypted before the scrypt upgrade still decrypt."""
    raw = os.getenv("SKIPPERBOT_SECRET_KEY", "").strip()
    if not raw:
        return []
    direct = _decoded_32(raw)
    if direct is not None:
        return [direct]
    keys = [_key()]                                          # scrypt (new)
    keys.append(hashlib.sha256(raw.encode("utf-8")).digest())  # legacy (old data)
    return [k for k in keys if k]


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
    keys = _decrypt_keys()
    if not keys:
        raise SecretKeyMissing(
            "SKIPPERBOT_SECRET_KEY is not set — cannot decrypt a stored secret."
        )
    try:
        blob = base64.urlsafe_b64decode(token[len(_PREFIX):])
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    except Exception as exc:
        raise SecretDecryptError("Stored secret is malformed.") from exc
    last_exc: Exception | None = None
    for key in keys:                       # try scrypt, then legacy sha256
        try:
            return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
        except Exception as exc:           # InvalidTag for the wrong key
            last_exc = exc
    raise SecretDecryptError(
        "Could not decrypt a stored secret — SKIPPERBOT_SECRET_KEY may have "
        "changed since it was saved, or the value is corrupt."
    ) from last_exc


def _restrict_to_owner(path) -> None:
    """Best-effort: make *path* readable only by its owner (audit #30).

    POSIX (incl. the Docker container): ``chmod 600``.
    Windows: ``os.chmod`` can't express POSIX modes — it only toggles the
    read-only bit and would leave the file world-readable. Use ``icacls`` to
    drop inherited ACLs and grant the current user alone. Both paths are
    wrapped so a failure never blocks startup.
    """
    if os.name == "nt":
        import getpass
        import subprocess
        try:
            user = getpass.getuser()
            if not user:
                return
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                check=False, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


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
    import pathlib as _pathlib
    # Harden .env permissions to owner-only (audit #30): it holds the master
    # secret key + DB/OpenAI creds and must not be group/world-readable.
    # Cross-platform (chmod on POSIX, icacls on Windows).
    try:
        _env = _pathlib.Path(env_path) if env_path else _pathlib.Path(".env")
        if _env.exists():
            _restrict_to_owner(_env)
    except Exception:
        pass

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
