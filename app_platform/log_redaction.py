"""Redact auth tokens out of HTTP access-log request lines (issue #7).

The WebSocket bearer token now rides the Sec-WebSocket-Protocol header rather than
the URL, but this is defense-in-depth: it guarantees no token — a ``/ws`` query
string, or a ``token=`` / ``access_token=`` / ``api_token=`` param anywhere — is
ever written to the ``uvicorn.access`` log, regardless of how the app is launched.
Installed from config.py so it applies under every runtime (uvicorn.run, gunicorn,
--reload, an external ASGI server).
"""

import logging
import re

# Mask the value of a known auth query param, e.g. ``token=abc`` -> ``token=***``.
_TOKEN_QS_RE = re.compile(r"((?:access_token|api_token|token)=)[^&\s\"']+")
# Mask the ENTIRE query string of any /ws upgrade line — the only place a token
# legitimately appeared in a URL here — so a future/renamed param can't re-leak.
_WS_QS_RE = re.compile(r"(/ws[^\s?\"']*)\?[^\s\"']*")
# Mask home-location query params (lat/lon/location) so the home location is
# never written to uvicorn.access — matching app_platform.location's guarantee
# that the home location is not logged. The leading lookbehind avoids matching a
# longer word ending in lat/lon (e.g. ``flat=``). The location string is already
# percent-encoded in the request line, so ``[^&\s"']+`` captures the whole value.
_GEO_QS_RE = re.compile(r"(?<![A-Za-z])((?:lat|lon|location)=)[^&\s\"']+")


def redact_access_log_line(text: str) -> str:
    """Mask any auth token OR home-location param in an access-log request line."""
    text = _WS_QS_RE.sub(r"\1?***", text)
    text = _TOKEN_QS_RE.sub(r"\1***", text)
    text = _GEO_QS_RE.sub(r"\1***", text)
    return text


class AccessLogTokenRedactor(logging.Filter):
    """Logging filter that scrubs tokens from access-log records in place.

    Operates generically on ``record.args`` (uvicorn formats the request line via
    args) and on ``record.msg``, so it is correct regardless of the exact access-log
    format string a self-hoster's server uses."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_access_log_line(a) if isinstance(a, str) else a
                for a in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                k: (redact_access_log_line(v) if isinstance(v, str) else v)
                for k, v in record.args.items()
            }
        if isinstance(record.msg, str):
            record.msg = redact_access_log_line(record.msg)
        return True


def install_access_log_redaction() -> None:
    """Attach the redactor to the ``uvicorn.access`` logger (idempotent)."""
    log = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogTokenRedactor) for f in log.filters):
        log.addFilter(AccessLogTokenRedactor())
