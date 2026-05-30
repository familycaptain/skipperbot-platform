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

# Console logging (existing behavior)
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("skipperbot")

# Quiet noisy third-party loggers
for _noisy in ("discord", "fakeredis", "mcp", "docket", "httpx", "httpcore", "openai"):
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
_file_handler.setLevel(logging.DEBUG)
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


def _platform_setting(key: str, default, cast=None):
    """Resolve a System-panel setting from app_config(scope=platform), else
    the hardcoded default. App settings are authoritative — no .env fallback.
    Guarded so a DB hiccup at import can never break config import (returns
    the default). Resolved once at import, so UI changes take effect on the
    next restart (fine for model names + debug flags).
    """
    try:
        from app_platform import settings as _settings
        val = _settings.get(key, scope="platform", default=None)
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
DEBUG_TOKENS = _platform_setting("debug_tokens", False, cast=_as_bool)
NAG_WAKE_HOUR = int(os.getenv("NAG_WAKE_HOUR", "8"))
NAG_SLEEP_HOUR = int(os.getenv("NAG_SLEEP_HOUR", "21"))

# Nag time-of-day slots (hours, 24h format). "evening" and "night" map to the same slot.
NAG_SLOTS = {
    "morning":   (int(os.getenv("NAG_MORNING_START", "7")),  int(os.getenv("NAG_MORNING_END", "12"))),
    "afternoon": (int(os.getenv("NAG_AFTERNOON_START", "12")), int(os.getenv("NAG_AFTERNOON_END", "17"))),
    "evening":   (int(os.getenv("NAG_EVENING_START", "17")), int(os.getenv("NAG_EVENING_END", "21"))),
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
SHOW_ENTITY_IDS = _platform_setting("show_entity_ids", False, cast=_as_bool)
REMINDER_LEAD_MINUTES = int(os.getenv("REMINDER_LEAD_MINUTES", "120"))
PM_QUIET_MODE = os.getenv("PM_QUIET_MODE", "false").lower() in ("true", "1", "yes")


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
    return "\n".join(parts)
