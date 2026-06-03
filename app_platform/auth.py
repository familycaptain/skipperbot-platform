"""Server-side authentication — bearer tokens for the platform API.

Two kinds of bearer credential, both presented as ``Authorization: Bearer <t>``
on HTTP and ``?token=<t>`` on websocket upgrades:

  * **Session tokens** — stateless, minted for a logged-in human at /auth/login.
    Format ``tok:1:<base64url(nonce || AES-256-GCM(json payload))>``. The payload
    is ``{sub, role, typ:"session", ver, iat, exp}``. Integrity + confidentiality
    come from AES-GCM; expiry (``exp``) and revocation (``ver`` vs the user's
    ``token_version``) are checked on verify. No DB row per token.

  * **Service tokens** — long-lived, opaque ``st_<random>`` strings for
    non-browser clients (the voice satellite, mobile). Stored hashed in
    ``public.service_tokens`` (see data_layer/service_tokens.py), so they're
    revocable and a DB leak can't replay them.

Signing key: ``SKIPPERBOT_AUTH_KEY`` (preferred) or ``SKIPPERBOT_SECRET_KEY``
(fallback). Kept separate from the at-rest secret key on purpose, so rotating
auth doesn't invalidate stored encrypted settings (and vice-versa). Same
key-handling rules as app_platform.secrets (32-byte urlsafe-b64, else SHA-256
of the passphrase).

Enforcement lives in the agent's HTTP middleware (sets ``request.state.principal``);
the FastAPI deps below read that (with a header fallback so they work standalone).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "tok:1:"
_NONCE_BYTES = 12
_SERVICE_PREFIX = "st_"

# Session lifetime; override with SKIPPERBOT_SESSION_TTL (seconds). Default 30 days.
SESSION_TTL = int(os.getenv("SKIPPERBOT_SESSION_TTL", str(30 * 24 * 3600)))


def _auth_key() -> bytes | None:
    """The 32-byte signing key (SKIPPERBOT_AUTH_KEY, else SKIPPERBOT_SECRET_KEY)."""
    raw = (os.getenv("SKIPPERBOT_AUTH_KEY", "").strip()
           or os.getenv("SKIPPERBOT_SECRET_KEY", "").strip())
    if not raw:
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def auth_key_available() -> bool:
    return _auth_key() is not None


def auth_enforced() -> bool:
    """Whether the API rejects unauthenticated requests.

    OFF by default so the whole auth layer can ship dormant and be flipped on
    (``SKIPPERBOT_AUTH_ENFORCE=1``) to test on a live host — and flipped back
    instantly if something misbehaves, with no redeploy. When off: tokens are
    still verified and the principal attached when present (so the new
    identity-derivation paths work), but missing/invalid tokens are NOT rejected
    and handlers fall back to legacy behavior.
    """
    return os.getenv("SKIPPERBOT_AUTH_ENFORCE", "").strip().lower() in ("1", "true", "yes", "on")


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Session tokens (stateless)
# ---------------------------------------------------------------------------

def mint_session_token(user: dict) -> str:
    """Mint a session token for a logged-in user dict (needs at least ``name``)."""
    key = _auth_key()
    if key is None:
        raise RuntimeError(
            "Cannot mint a session token: neither SKIPPERBOT_AUTH_KEY nor "
            "SKIPPERBOT_SECRET_KEY is set."
        )
    payload = {
        "sub": user["name"],
        "role": user.get("role", "") or "",
        "typ": "session",
        "ver": int(user.get("token_version", 0) or 0),
        "iat": _now(),
        "exp": _now() + SESSION_TTL,
    }
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, json.dumps(payload).encode("utf-8"), None)
    return _PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def _verify_session(token: str) -> dict | None:
    key = _auth_key()
    if key is None or not token.startswith(_PREFIX):
        return None
    try:
        blob = base64.urlsafe_b64decode(token[len(_PREFIX):])
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        payload = json.loads(AESGCM(key).decrypt(nonce, ct, None).decode("utf-8"))
    except Exception:
        return None  # bad key, tampered, malformed
    if payload.get("typ") != "session" or int(payload.get("exp", 0)) < _now():
        return None
    # Confirm the user still exists and the token hasn't been revoked.
    try:
        from data_layer.users import get_user
        u = get_user(payload.get("sub", "") or "")
    except Exception:
        return None
    if not u:
        return None
    if int(u.get("token_version", 0) or 0) != int(payload.get("ver", 0) or 0):
        return None  # revoked (token_version bumped)
    return {"name": u["name"], "role": u.get("role", "") or "",
            "typ": "session", "is_service": False}


# ---------------------------------------------------------------------------
# Service tokens (DB-backed)
# ---------------------------------------------------------------------------

def _verify_service(token: str) -> dict | None:
    if not token.startswith(_SERVICE_PREFIX):
        return None
    try:
        from data_layer.service_tokens import verify_token_hash
        return verify_token_hash(token)
    except Exception:
        return None


def verify_token(token: str | None) -> dict | None:
    """Resolve any bearer token to a principal dict, or None if invalid.

    Principal: ``{"name", "role", "typ": "session"|"service", "is_service": bool}``.
    """
    if not token:
        return None
    token = token.strip()
    if token.startswith(_SERVICE_PREFIX):
        return _verify_service(token)
    return _verify_session(token)


# ---------------------------------------------------------------------------
# Request / WebSocket extractors
# ---------------------------------------------------------------------------

def _bearer(header_value: str | None) -> str | None:
    if header_value and header_value.lower().startswith("bearer "):
        return header_value[7:].strip()
    return None


def principal_from_request(request) -> dict | None:
    """Verify the Authorization: Bearer token on an HTTP request."""
    return verify_token(_bearer(request.headers.get("authorization")))


def principal_from_ws(websocket) -> dict | None:
    """Verify a websocket's ``?token=`` (or Authorization header for native clients)."""
    tok = websocket.query_params.get("token")
    if tok:
        return verify_token(tok)
    return verify_token(_bearer(websocket.headers.get("authorization")))


# ---------------------------------------------------------------------------
# FastAPI dependencies + authorization helpers
# ---------------------------------------------------------------------------

def require_user(request) -> dict:
    """FastAPI dependency: the authenticated principal, or 401.

    Reads ``request.state.principal`` (set by the auth middleware) and falls back
    to verifying the header directly, so it works even if the middleware is absent.
    """
    from fastapi import HTTPException
    principal = getattr(request.state, "principal", None) or principal_from_request(request)
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def require_admin(request) -> dict:
    """FastAPI dependency: principal with the admin role, or 401/403."""
    from fastapi import HTTPException
    from data_layer.users import has_role
    principal = require_user(request)
    if not has_role(principal, "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return principal


def current_principal(request) -> dict | None:
    """The authenticated principal attached by the middleware, or None."""
    return getattr(request.state, "principal", None)


def enforce_admin(request) -> None:
    """Require an admin principal when enforcement is on; no-op when off.

    For endpoints that previously had NO auth (so legacy behavior must be
    preserved until the flag flips)."""
    from fastapi import HTTPException
    from data_layer.users import has_role
    if auth_enforced():
        p = current_principal(request)
        if not (p and has_role(p, "admin")):
            raise HTTPException(status_code=403, detail="Admin access required")


def scope_user(request, requested_user_id: str | None) -> str:
    """Whose data the caller may act on.

    With a verified principal: self by default, another user only for
    admin/parent (IDOR guard). Without one (enforcement off / no token): the
    legacy client-supplied value, lowercased — preserving pre-auth behavior.
    """
    p = current_principal(request)
    if p is None:
        return (requested_user_id or "").lower().strip()
    return resolve_target(p, requested_user_id)


def resolve_target(principal: dict, requested_user_id: str | None) -> str:
    """Return whose data the caller may act on.

    Defaults to the caller themselves. Targeting another user is allowed only for
    admin/parent roles (IDOR guard) — otherwise 403.
    """
    from fastapi import HTTPException
    from data_layer.users import has_any_role
    me = (principal.get("name") or "").lower().strip()
    req = (requested_user_id or "").lower().strip()
    if not req or req == me:
        return me
    if has_any_role(principal, "admin", "parent"):
        return req
    raise HTTPException(status_code=403, detail="Cannot access another user's data")
