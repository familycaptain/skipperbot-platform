"""
SkipperBot Configuration
Logging, environment, OpenAI client, and system prompt loading.
"""

import os
import shutil
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Console logging. INFO by default; set LOG_LEVEL=DEBUG in .env for verbose output.
_LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(level=_LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("skipperbot")

# Quiet noisy third-party loggers. websockets is capped because at DEBUG it logs
# the full WS handshake — including the 'Authorization: Bearer <key>' header.
for _noisy in ("discord", "fakeredis", "mcp", "docket", "httpx", "httpcore", "openai",
               "websockets", "websockets.client", "websockets.server"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# Windows-safe rotating handler: falls back to copy+truncate when os.rename is blocked
class _WinSafeRotatingHandler(TimedRotatingFileHandler):
    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        try:
            super().doRollover()
        except PermissionError:
            try:
                import time as _time
                t = self.rolloverAt - self.interval
                dfn = self.rotation_filename(
                    self.baseFilename + "." + _time.strftime(self.suffix, _time.localtime(t))
                )
                shutil.copy2(self.baseFilename, dfn)
                open(self.baseFilename, "w").close()  # noqa: WPS515
                self.rolloverAt = self.computeRollover(int(_time.time()))
            except Exception:
                pass
        if not self.stream:
            self.stream = self._open()


# File logging — daily rotation, 14-day retention
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_file_handler = _WinSafeRotatingHandler(
    os.path.join(_LOG_DIR, "skipperbot.log"),
    when="midnight",
    backupCount=14,
    encoding="utf-8",
    delay=True,
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
_file_handler.setLevel(_LOG_LEVEL)
logging.getLogger().addHandler(_file_handler)

# PM audit logger — separate file for daily review of PM actions
pm_audit_logger = logging.getLogger("pm_audit")
pm_audit_logger.setLevel(logging.INFO)
_pm_handler = _WinSafeRotatingHandler(
    os.path.join(_LOG_DIR, "pm_audit.log"),
    when="midnight",
    backupCount=30,
    encoding="utf-8",
    delay=True,
)
_pm_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
pm_audit_logger.addHandler(_pm_handler)
pm_audit_logger.propagate = False  # don't duplicate to main log

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def _platform_setting(key: str, default, cast=None, scope: str = "platform"):
    """Resolve a setting from app_config (default scope=platform; pass an
    app scope like "app:reminders" for app-owned tuning), else the hardcoded
    default. App settings are authoritative — no .env fallback. Guarded so a
    DB hiccup at import can never break config import (returns the default).
    Resolved once at import, so UI changes take effect on the next restart
    (fine for model names, debug flags, and tuning constants).
    """
    try:
        from app_platform import settings as _settings
        val = _settings.get(key, scope=scope, default=None)
    except Exception:
        val = None
    if val in (None, ""):
        return default
    if cast:
        try:
            return cast(val)
        except Exception:
            return default
    return val


SMART_MODEL = _platform_setting("smart_model", "gpt-5.2")
DUMB_MODEL = _platform_setting("dumb_model", "gpt-5-mini")
OPENAI_MODEL = SMART_MODEL  # backward compat alias
DEBUG_TOKENS = _platform_setting("debug_tokens", True, cast=_as_bool)
# Nag timing — configured in Settings → Notifications (scope=app:notifications),
# resolved at import (restart to change). Guarded fall-back to the defaults.
_nag = lambda key, default: _platform_setting(key, default, cast=int, scope="app:notifications")
NAG_WAKE_HOUR = _nag("nag_wake_hour", 8)
NAG_SLEEP_HOUR = _nag("nag_sleep_hour", 21)

# Nag time-of-day slots (hours, 24h format). "evening" and "night" map to the same slot.
NAG_SLOTS = {
    "morning":   (_nag("nag_morning_start", 7),  _nag("nag_morning_end", 12)),
    "afternoon": (_nag("nag_afternoon_start", 12), _nag("nag_afternoon_end", 17)),
    "evening":   (_nag("nag_evening_start", 17), _nag("nag_evening_end", 21)),
}
NAG_SLOTS["night"] = NAG_SLOTS["evening"]  # alias

# Discord is an OPTIONAL integration. We only turn it on when the user
# has actually supplied a token, OR explicitly flips the enable toggle.
# Default-on caused first-time installs to log "Discord ready" followed
# immediately by "No token — bot disabled" noise that looked like a failure.
#
# Resolved at call time from the Settings "Integrations" panel
# (scope=platform). It's a function (not a module constant) because the value
# changes at runtime via the UI, and to avoid a DB read at import time.
def discord_enabled() -> bool:
    from app_platform import settings as _settings
    explicit = _settings.get("discord_enabled", scope="platform", default=False)
    if str(explicit).lower() in ("true", "1", "yes") or explicit is True:
        return True
    # Enabled implicitly if a token has been saved.
    return _settings.is_configured("discord_token", scope="platform")
SHOW_ENTITY_IDS = _platform_setting("show_entity_ids", True, cast=_as_bool)
# App-owned tuning: configured in Settings → Reminders / Settings → Goals.
REMINDER_LEAD_MINUTES = _platform_setting("reminder_lead_minutes", 120, cast=int, scope="app:reminders")
# Concrete times the agent uses to resolve fuzzy reminder phrasing ("tomorrow
# morning" → REMINDER_MORNING_SLOT). Surfaced into the system prompt below.
REMINDER_MORNING_SLOT = _platform_setting("default_morning_slot", "08:00", scope="app:reminders")
REMINDER_AFTERNOON_SLOT = _platform_setting("default_afternoon_slot", "13:00", scope="app:reminders")
REMINDER_EVENING_SLOT = _platform_setting("default_evening_slot", "19:00", scope="app:reminders")
PM_QUIET_MODE = _platform_setting("pm_quiet_mode", False, cast=_as_bool, scope="app:goals")


# ---------------------------------------------------------------------------
# Entity prefix registry — source of truth for {{ENTITY_PREFIX_TABLE}}
# Add new entity types here; BEHAVIOR.md will reflect them automatically.
# ---------------------------------------------------------------------------

ENTITY_PREFIXES: list[tuple[str, list[tuple[str, str]]]] = [
    ("Core", [
        ("g-",   "Goal"),
        ("p-",   "Project"),
        ("t-",   "Task"),
        ("r-",   "Reminder"),
        ("j-",   "Job"),
        ("sch-", "Schedule"),
        ("sc-",  "Schedule Completion"),
        ("n-",   "Notification"),
        ("pf-",  "Priority Focus"),
    ]),
    ("Content", [
        ("l-",   "List"),
        ("li-",  "List Item"),
        ("d-",   "Document"),
        ("a-",   "Artifact"),
        ("i-",   "Image"),
        ("fld-", "Folder"),
    ]),
    ("Memory & Knowledge", [
        ("m-",   "Memory"),
        ("k-",   "Knowledge Source"),
        ("kc-",  "Knowledge Crawl"),
        ("c-",   "Chat Log"),
        ("lnk-", "Link"),
    ]),
    ("Productivity", [
        ("si-",  "Scrum Item"),
        ("iss-", "Issue"),
        ("bs-",  "Idea"),
        ("bp-",  "Idea Part"),
        ("ev-",  "Evolution Item"),
        ("et-",  "Evolution Thread"),
    ]),
    ("Recipes & Meals", [
        ("re-",  "Recipe"),
        ("cat-", "Recipe Category"),
        ("ml-",  "Meal"),
        ("mc-",  "Meal Component"),
        ("mcu-", "Meal Cuisine"),
        ("mtg-", "Meal Tag"),
    ]),
    ("Medical", [
        ("mmbr-",  "Medical Member"),
        ("mevt-",  "Medical Event"),
        ("mmed-",  "Medication"),
        ("mtrx-",  "Treatment"),
        ("mtrxl-", "Treatment Log"),
        ("mlbt-",  "Lab Test"),
        ("mlbr-",  "Lab Result"),
    ]),
    ("Home & Vehicle", [
        ("hmt-",  "Home Task"),
        ("hmtl-", "Home Task Log"),
        ("hi-",   "Home Issue"),
        ("svc-",  "Service Record"),
        ("veh-",  "Vehicle"),
        ("vis-",  "Vehicle Issue"),
        ("vcon-", "Vehicle Condition"),
        ("vval-", "Vehicle Valuation"),
    ]),
    ("Homeopathy", [
        ("hmed-",  "Homeo Medicine"),
        ("hrem-",  "Homeo Remedy"),
        ("hbot-",  "Homeo Bottle"),
        ("hsize-", "Homeo Bottle Size"),
        ("hloc-",  "Homeo Location"),
        ("hsrc-",  "Homeo Source"),
    ]),
    ("Investment", [
        ("iacct-",  "Investment Account"),
        ("istrat-", "Investment Strategy"),
        ("irun-",   "Research Run"),
        ("isnap-",  "Investment Snapshot"),
        ("ieq-",    "Equity Curve Tick"),
        ("ec-",     "Equity Curve"),
    ]),
    ("Timeline", [
        ("tp-",  "Timeline Post"),
        ("tph-", "Timeline Photo"),
    ]),
    ("Email", [
        ("ea-", "Email Account"),
        ("er-", "Email Rule"),
        ("el-", "Email Log Entry"),
    ]),
    ("Other", [
        ("loc-",  "Located Item"),
        ("iloc-", "Item Location"),
        ("b-",    "Backup"),
        ("tl-",   "Thinking Log"),
        ("ss-",   "Skipper State"),
    ]),
]


def _build_entity_prefix_table() -> str:
    """Generate the entity prefix markdown table from ENTITY_PREFIXES."""
    lines = ["| Prefix | Type |", "|--------|------|"]
    for group, prefixes in ENTITY_PREFIXES:
        lines.append(f"| **{group}** | |")
        for prefix, entity_type in prefixes:
            lines.append(f"| {prefix} | {entity_type} |")
    return "\n".join(lines)


def _build_tool_category_list() -> str:
    """Build a comma-delimited list of all available tool categories.

    Uses a lazy import of tool_router to avoid circular dependencies.
    App categories appear as 'app:auto', 'app:home', etc.
    """
    try:
        import tool_router  # noqa: PLC0415 — intentional lazy import
        cats = list(tool_router.TOOL_CATEGORIES.keys())
    except Exception:
        cats = []
    return ", ".join(cats) if cats else "(categories not yet loaded)"


def apply_prompt_templates(text: str) -> str:
    """Replace {{PLACEHOLDER}} tokens in a prompt string with live values.

    Recognized tokens:
      {{ENTITY_PREFIX_TABLE}}  — full markdown table of entity type prefixes
      {{TOOL_CATEGORY_LIST}}   — comma-delimited list of all tool categories
    """
    text = text.replace("{{ENTITY_PREFIX_TABLE}}", _build_entity_prefix_table())
    text = text.replace("{{TOOL_CATEGORY_LIST}}", _build_tool_category_list())
    return text


# ---------------------------------------------------------------------------
# System prompt cache
# Dynamic content (timestamp, user_id) is provided separately via
# get_dynamic_system_context() so the static prefix can be cached by OpenAI.
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT: str | None = None


def invalidate_system_prompt() -> None:
    """Clear the cached base system prompt so it is rebuilt on the next call.

    Call this after tool categories change (e.g. after app packages are loaded)
    so the injected {{TOOL_CATEGORY_LIST}} reflects the latest categories.
    """
    global _BASE_SYSTEM_PROMPT
    _BASE_SYSTEM_PROMPT = None


def load_system_prompt(user_id: str = "") -> str:
    """Return the STATIC base system prompt (cacheable).

    Reads SOUL.md, BEHAVIOR.md, etc. once, applies {{PLACEHOLDER}} template
    substitutions, then caches the result. Call invalidate_system_prompt() to
    force a rebuild (e.g. after app packages finish loading).

    Does NOT include timestamps or user-specific context — those go in the
    dynamic context via get_dynamic_system_context().
    """
    global _BASE_SYSTEM_PROMPT
    if _BASE_SYSTEM_PROMPT is None:
        parts = []
        for filename in ["SOUL.md", "BEHAVIOR.md", "MEMORY.md", "KNOWLEDGE.md", "DISCORD.md"]:
            filepath = os.path.join(PROMPTS_DIR, filename)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    parts.append(f.read().strip())
        parts.append(f"REMINDER_LEAD_MINUTES: {REMINDER_LEAD_MINUTES}")
        parts.append(
            "REMINDER_TIME_SLOTS (use these concrete local times when a reminder "
            "request gives only a vague time of day): "
            f"morning={REMINDER_MORNING_SLOT}, afternoon={REMINDER_AFTERNOON_SLOT}, "
            f"evening={REMINDER_EVENING_SLOT} (night → evening)."
        )
        raw = "\n\n".join(parts)
        _BASE_SYSTEM_PROMPT = apply_prompt_templates(raw)
    return _BASE_SYSTEM_PROMPT


def get_dynamic_system_context(user_id: str = "") -> str:
    """Return per-call dynamic context (timestamp, user_id).

    Callers should place this in a SECOND system message after the static
    prompt so the static prefix can be cached by OpenAI.
    """
    from app_platform.time import now as _platform_now, get_timezone

    user_now = _platform_now(user_id or None)
    tz = get_timezone(user_id or None)
    parts = [
        f"Current date and time: {user_now.strftime('%A, %B %d, %Y at %I:%M %p')} ({tz.key})",
    ]
    if user_id:
        parts.append(f"You are currently talking to: {user_id}")

    # Home ZIP code (Settings → System → Default ZIP code). Surfacing it here
    # lets the assistant answer "what's my zip?" and pass it to the weather
    # tools instead of guessing a location. Read live so it works without a
    # restart. Best-effort — never break context assembly over it.
    try:
        from app_platform import settings as _settings
        # str() — the stored value can come back as an int (e.g. 72956), and
        # int.strip() would raise (and the old silent except hid it).
        _zip = str(_settings.get("default_zip", scope="platform", default="") or "").strip()
        if _zip:
            parts.append(
                f"The user's home ZIP code is {_zip}. Use it for weather and other "
                f"location lookups when they don't specify one — never invent a location."
            )
    except Exception:
        logger.warning("dynamic context: default_zip lookup failed", exc_info=True)

    # Primary user — the person who installed/owns this Skipper. Lets onboarding
    # and proactive outreach know who to engage (onboarding is about this person).
    try:
        from data_layer.users import get_primary_user
        _primary = get_primary_user()
        if _primary:
            parts.append(
                f"The primary user (the person who installed and owns this Skipper) is "
                f"'{_primary}'. Onboarding and proactive outreach are about helping them."
            )
    except Exception:
        logger.warning("dynamic context: primary_user lookup failed", exc_info=True)

    return "\n".join(parts)
