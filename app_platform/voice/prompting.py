"""
Shared voice prompt and tool configuration.

This module is the common source of truth for voice instructions and tool
schemas used by both the Android voice client and the home voice service.
"""

from __future__ import annotations

import os
import importlib
import inspect
from pathlib import Path
from typing import Iterable

from config import PROMPTS_DIR, apply_prompt_templates
from app_platform.time import get_timezone
from app_platform.prompt_context import collect_prompt_context


GLOBAL_CATEGORIES = {"core", "utility", "web", "knowledge", "filesystem", "timers"}

# Curated VOICE-CORE categories: app tools ALWAYS loaded at the start of EVERY voice
# session, so the most common quick asks work WITHOUT first saying "open the <app> app"
# ("what's the weather", "remind me…", "turn on the lights", "any notifications?").
# Keep this list SMALL and curated — every category here adds tools to the always-on
# voice prompt, which is exactly what the open-the-XYZ-app JIT loading exists to avoid.
# Everything NOT listed stays behind request_tools / "open the <app> app" (auto, medical,
# home-maintenance, etc.). Tune to the most common voice use cases.
VOICE_CORE_CATEGORIES = {"weather", "automation", "reminders", "notifications"}

HOME_VOICE_DEFAULT_CATEGORIES = {"automation"}  # extra categories for home voice devices

# Tools NEVER worth carrying in the always-on voice prompt — dev / filesystem / admin /
# knowledge-base management. Nobody greps files, validates YAML, or manages knowledge
# crawls by voice, yet these (from the filesystem/utility globals) were ~half the voice
# tool budget. Excluded from the voice tool set to keep the Realtime context lean; they
# remain available on the chat/text surface. Tune freely.
VOICE_TOOL_EXCLUDE = {
    # filesystem / file ops
    "cat_file", "tail_file", "ls_dir", "glob_search", "grep_search", "os_level_find",
    # dev / code / introspection
    "json_validate_file", "yaml_validate_file", "git_tool", "read_feature_spec", "list_all_tools",
    # network / admin
    "curl_request", "ping_host", "restart_agent",
    # knowledge-base management (query_knowledge/recall/remember stay)
    "learn_from_url", "list_knowledge_crawls", "list_knowledge_sources",
    "get_knowledge_crawl", "remove_knowledge_source",
    # misc dev/test
    "echo",
}
BASE_DIR = Path(__file__).resolve().parent
APPS_DIR = BASE_DIR / "apps"


LEGACY_APP_ALIASES = {
    "goals": "goals",
    "tasks": "goals",
    "investment": "investment",
    "investments": "investment",
    "lists": "lists",
    "todo": "lists",
    "reminders": "reminders",
    "calendar": "reminders",
    "schedules": "reminders",
    "documents": "docs",
    "folders": "docs",
    "finder": "docs",
    "jobs": "jobs",
    "system": "system",
    "tools": "system",
    "prioritize": "prioritize",
}


def load_personality_prompt() -> str:
    """Load the base personality prompt used by voice sessions."""
    path = os.path.join(PROMPTS_DIR, "BEHAVIOR.md")
    try:
        with open(path, encoding="utf-8") as f:
            behavior = apply_prompt_templates(f.read())
    except FileNotFoundError:
        behavior = "You are Skipper, a helpful family assistant."

    discord_path = os.path.join(PROMPTS_DIR, "DISCORD.md")
    try:
        with open(discord_path, encoding="utf-8") as f:
            behavior += "\n\n" + f.read()
    except FileNotFoundError:
        pass

    return behavior


def build_base_voice_payload(user_id: str = "", device_info: dict | None = None) -> dict:
    """Build base voice instructions and tools for a device."""
    device_info = device_info or {}
    default_categories = get_default_categories(device_info)
    tools = build_voice_tools(default_categories)
    instructions = build_base_voice_instructions(
        user_id=user_id,
        device_info=device_info,
        default_categories=default_categories,
    )

    return {
        "instructions": instructions,
        "tools": tools,
        "app": "automation" if is_home_voice_device(device_info) else None,
        "category": "automation" if is_home_voice_device(device_info) else None,
        "default_categories": sorted(default_categories),
    }


def available_voice_apps() -> list[str]:
    """Return app/category names voice can switch to, from shared route sources."""
    names = set(LEGACY_APP_ALIASES.keys())
    names.update(discover_app_package_categories(include_keywords=False).keys())

    try:
        from tool_router import TOOL_CATEGORIES

        for category in TOOL_CATEGORIES:
            if category in GLOBAL_CATEGORIES:
                continue
            names.add(category.removeprefix("app:"))
    except Exception:
        pass

    return sorted(names)


def available_voice_apps_text() -> str:
    return ", ".join(available_voice_apps())


def discover_app_package_categories(*, include_keywords: bool = True) -> dict[str, str]:
    """Map app ids, names, and keywords to app package categories."""
    aliases: dict[str, str] = {}
    if not APPS_DIR.is_dir():
        return aliases

    for manifest_path in APPS_DIR.glob("*/manifest.yaml"):
        app_dir = manifest_path.parent
        if not (app_dir / "tools.py").exists():
            continue
        try:
            import yaml

            with open(manifest_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            continue

        app_id = normalize_app_name(str(raw.get("id") or app_dir.name))
        if not app_id:
            continue

        aliases[app_id] = app_id
        app_name = normalize_app_name(str(raw.get("name") or ""))
        if app_name:
            aliases[app_name] = app_id

        if include_keywords:
            tool_category = raw.get("tool_category") or {}
            for keyword in tool_category.get("keywords") or []:
                normalized = normalize_app_name(str(keyword))
                if normalized:
                    aliases.setdefault(normalized, app_id)

    return aliases


def build_app_voice_payload(
    app_name: str,
    *,
    user_id: str = "",
    device_info: dict | None = None,
) -> dict:
    """Build a session.update payload for an app-specific voice mode."""
    device_info = device_info or {}
    app_key = normalize_app_name(app_name)
    category = resolve_app_category(app_key)

    if not category:
        return {
            "error": f"Unknown app: {app_name}",
            "available_apps": available_voice_apps(),
        }

    personality = load_personality_prompt()
    guide = load_guide(category) or ""
    time_context = build_current_time_context()
    location_context = build_voice_location_context()
    device_context = build_device_context(device_info)
    user_context = build_voice_user_context(user_id, device_info)
    behavior_rules = build_active_behavior_rules(user_id)
    language_rules = build_voice_language_rules()
    app_routing_rules = build_voice_app_routing_rules()
    messaging_rules = build_voice_messaging_rules()
    memory_rules    = build_voice_memory_rules(user_id, device_info)
    tool_ack_rules  = build_voice_tool_ack_rules()

    # App-specific blocks. The automation app gets a compact list of HA
    # aliases so the model knows which friendly names are real callable
    # targets — prevents the "what's the temperature outside" hallucination
    # where it didn't realize a sensor named "outside" actually exists.
    extra_blocks = collect_prompt_context(
        "voice", app_key=app_key, user_id=user_id, device_info=device_info
    )

    instructions = (
        f"{personality}\n\n"
        "---\n"
        f"## Active App: {app_key.title()}\n"
        "You are in a voice conversation. Keep responses concise and conversational.\n"
        "The user can say 'go to [app name]' to switch apps, or 'exit'/'base mode' "
        "to return to the default voice mode.\n"
        "Do not use the open_app tool for voice app switching. Use switch_voice_app instead.\n"
        f"{time_context}"
        f"{location_context}"
        f"{device_context}"
        f"{user_context}"
        f"{behavior_rules}"
        f"{language_rules}"
        f"{app_routing_rules}"
        f"{messaging_rules}"
        f"{tool_ack_rules}"
        f"{memory_rules}"
        f"{extra_blocks}\n"
        f"### {app_key.title()} Guide\n\n{guide}"
    )

    tools = build_voice_tools({category})
    return {
        "instructions": instructions,
        "tools": tools,
        "app": app_key,
        "category": category,
    }


def build_exit_voice_payload(user_id: str = "", device_info: dict | None = None) -> dict:
    """Build a payload for returning to the device's default voice mode."""
    return build_base_voice_payload(user_id=user_id, device_info=device_info)


def build_base_voice_instructions(
    *,
    user_id: str = "",
    device_info: dict | None = None,
    default_categories: set[str] | None = None,
) -> str:
    device_info = device_info or {}
    default_categories = default_categories or get_default_categories(device_info)
    personality = load_personality_prompt()
    time_context = build_current_time_context()
    location_context = build_voice_location_context()
    device_context = build_device_context(device_info)
    user_context = build_voice_user_context(user_id, device_info)
    behavior_rules = build_active_behavior_rules(user_id)
    language_rules = build_voice_language_rules()
    app_routing_rules = build_voice_app_routing_rules()
    messaging_rules = build_voice_messaging_rules()
    memory_rules   = build_voice_memory_rules(user_id, device_info)
    tool_ack_rules = build_voice_tool_ack_rules()
    default_guides = load_guides(default_categories)

    if is_home_voice_device(device_info):
        mode = (
            "## Home Voice Mode\n"
            "You are in a voice conversation through a physical home speakerphone. "
            "Keep responses concise, natural, and easy to hear across a room.\n"
            "Start in the Automation voice app by default, with the automation tool guide loaded. "
            "When the user says 'open [app]', 'go to [app]', or 'switch to [app]', "
            "use switch_voice_app to load that app's voice tools and guide. "
            "Do not use the open_app tool for voice app switching because that opens "
            "the desktop web UI, not the voice tool context. "
            f"Available voice apps: {available_voice_apps_text()}.\n"
            "For ambiguous automation commands like 'turn on the light', use the room "
            "context when it is available and safe.\n"
            "For dangerous, expensive, security-related, or irreversible actions, "
            "require explicit confirmation or refuse when appropriate.\n"
        )
    else:
        mode = (
            "## Voice Mode\n"
            "You are in a voice conversation on the user's phone. Keep responses "
            "concise and conversational.\n"
            "When the user says 'open [app]', 'go to [app]', or 'switch to [app]', "
            "they mean they want to load that app's tools so you can help with "
            "app-specific tasks. Do not use the open_app tool for this because it "
            "opens the desktop web UI, not the voice tools.\n"
            f"Available apps: {available_voice_apps_text()}.\n"
            "In base mode you can answer general questions and send messages. "
            "For app-specific actions, suggest the user switch to the right app.\n"
        )

    ending_rules = (
        "\n## Critical: Ending The Session\n"
        "When the user says 'goodbye', 'bye', 'I'm done', 'that's all', 'stop', "
        "'see you later', 'thanks that's it', or any farewell/sign-off phrase:\n"
        "- Immediately call the end_voice_session tool.\n"
        "- Do not speak first. Do not say goodbye. Do not generate audio first.\n"
        "- The client will play an end tone to confirm.\n"
    )

    guide_block = ""
    if default_guides:
        guide_block = "\n\n## Default Voice Guides\n\n" + default_guides

    return (
        f"{personality}\n\n"
        "---\n"
        f"{mode}"
        f"{time_context}"
        f"{location_context}"
        f"{device_context}"
        f"{user_context}"
        f"{behavior_rules}"
        f"{language_rules}"
        f"{app_routing_rules}"
        f"{messaging_rules}"
        f"{tool_ack_rules}"
        f"{memory_rules}"
        f"{ending_rules}"
        f"{guide_block}"
    )


def build_current_time_context() -> str:
    """Inject the current wall-clock time so the model can resolve relative phrases.

    Without this, voice ("remind me in 1 hour") had no ground truth for "now" and
    the model would hallucinate the current time. Realtime sessions are minted
    fresh on each wake-word detection, so this stays accurate per conversation.
    """
    from datetime import datetime

    now = datetime.now(get_timezone())
    return (
        "\n## Current Time\n"
        f"- {now.strftime('%A, %B %d, %Y at %I:%M %p')} Central Time "
        f"({now.strftime('%Y-%m-%dT%H:%M:%S%z')})\n"
        "- Use this when resolving relative times like 'in 1 hour', 'tomorrow', "
        "or 'tonight'. Do not guess the current time.\n"
    )


def build_voice_location_context() -> str:
    """Inject the user's home location so voice can answer weather/location queries.

    Mirrors the web chat's dynamic context (config.get_dynamic_system_context):
    resolved live via the platform location service (the canonical
    'City, Region, CountryName' label, no per-call geocoding). Best-effort;
    never break prompt assembly over it.
    """
    try:
        from app_platform.location import resolve_location, display_label

        record = resolve_location()
        label = display_label(record) if record.get("configured") else ""
    except Exception:
        return ""
    if not label:
        return ""
    return (
        "\n## Home Location\n"
        f"- The user's home location is {label}. Use it for weather and other "
        "location lookups when they don't specify one — never invent a location.\n"
    )


def build_device_context(device_info: dict | None) -> str:
    device_info = device_info or {}
    platform = str(device_info.get("platform") or "unknown")
    device_id = str(device_info.get("device_id") or "").strip()
    room = str(device_info.get("room") or "").strip()
    friendly_name = str(device_info.get("friendly_name") or "").strip()

    lines = [
        "\n## Device Context",
        f"- Platform: {platform}",
    ]
    if friendly_name:
        lines.append(f"- Device name: {friendly_name}")
    if device_id:
        lines.append(f"- Device ID: {device_id}")
    if room:
        lines.append(f"- Room: {room}")
        lines.append("- For ambiguous home-control requests, prefer this room when safe.")
    return "\n".join(lines) + "\n"


def build_voice_user_context(user_id: str = "", device_info: dict | None = None) -> str:
    """Build compact speaker identity guidance for voice sessions."""
    device_info = device_info or {}
    user = (user_id or "").strip().lower()
    shared_device = is_home_voice_device(device_info)

    lines = ["\n## Voice User Context"]
    if user:
        lines.append(f"- Current session user: {user}")
        lines.append(
            "- Treat first-person words like I, me, and my as this user unless "
            "the speaker explicitly identifies someone else."
        )
    else:
        lines.append("- Current session user: unknown.")
        lines.append("- Ask who is speaking before answering personal or private requests.")

    if shared_device:
        lines.append(
            "- This is a shared home speaker. For sensitive personal data or actions, "
            "ask who is speaking if identity is ambiguous."
        )
    return "\n".join(lines) + "\n"


def build_active_behavior_rules(user_id: str = "") -> str:
    """Inject always-on user behavior rules into static voice instructions."""
    normalized_user = (user_id or "").strip().lower()
    if not normalized_user:
        return ""

    try:
        from app_platform.behaviors import get_active_behaviors_for_user

        active_behaviors = get_active_behaviors_for_user(normalized_user)
    except Exception:
        return ""

    if not active_behaviors:
        return ""

    lines = [
        "\n## Active Behavior Rules",
        "These rules are ALWAYS active. When a user message matches a trigger, "
        "perform the action immediately without being asked. Do not repeat the "
        "rule back to the user; just execute the action.",
        "",
    ]
    for behavior in active_behaviors:
        trigger = str(behavior.get("trigger_description") or "").strip()
        action = str(behavior.get("action_description") or "").strip()
        if not trigger or not action:
            continue
        lines.append(f"- Trigger: {trigger}")
        lines.append(f"  Action: {action}")
        lines.append("")

    return "\n".join(lines) + "\n"


def build_voice_language_rules() -> str:
    """Build compact language guidance for voice sessions."""
    return (
        "\n## Voice Language\n"
        "- Assume the speaker is using English, even when audio is noisy, clipped, "
        "or ambiguous.\n"
        "- Always respond in English unless the user clearly and explicitly asks "
        "to use another language.\n"
        "- Do not switch languages based only on uncertain transcription, "
        "background noise, accents, or short ambiguous phrases.\n"
        "- If the language is unclear, ask a brief clarifying question in English.\n"
    )


def build_voice_app_routing_rules() -> str:
    """Build compact app-switching guidance for voice sessions."""
    return (
        "\n## Voice App Routing\n"
        "- If the user explicitly asks to open, go to, or switch to an app, call "
        "switch_voice_app with that app name.\n"
        "- If the user's request is unrelated to the current active app or tool "
        "guide, use list_all_tools or get_guide() to check available tool "
        "categories/guides, then switch to the most relevant app before answering.\n"
        "- When the right app is clear, switch automatically without asking, "
        "then continue using that app's tools. The user does not need to say "
        "'open app' first.\n"
        "- In voice mode, switch_voice_app is what loads a new Realtime tool "
        "set. Do not use open_app for voice routing.\n"
        "- Use memory recall for remembered facts, preferences, and prior "
        "conversations; use app tools for live structured app data.\n"
        "- Ask a clarifying question only when the target app is genuinely "
        "ambiguous.\n"
        "- **Never use create_tool to invent a tool that might already exist "
        "in another app.** If you reference a tool name that isn't in your "
        "current toolset, FIRST call list_all_tools or switch_voice_app to "
        "load the relevant app — the tool you want almost certainly already "
        "exists there. create_tool is reserved for genuinely new capabilities "
        "no existing app provides.\n"
    )


def build_voice_messaging_rules() -> str:
    """Build compact messaging guidance for voice sessions."""
    return (
        "\n## Voice Messaging\n"
        "- When the user asks you to tell, message, notify, or send something "
        "to another person, use send_notification.\n"
        "- Do not choose a delivery channel such as Discord, Pushover, web, or "
        "mobile yourself. The Skipper notification service routes and logs it.\n"
    )


def build_voice_tool_ack_rules() -> str:
    """Tell the model to verbally acknowledge before any slow tool call so
    the user isn't left in awkward silence during multi-second tool I/O.

    The realtime model can output audio AND a function call in the SAME
    response — the audio streams to the user immediately while the tool
    dispatches in parallel. Web chat has the same UX via `send_progress`
    interim messages; this is voice's equivalent.
    """
    return (
        "\n## Voice Pacing — Acknowledge Before Slow Tools\n"
        "When you are about to call a tool that may take more than ~1 second, "
        "SPEAK A BRIEF ACKNOWLEDGMENT FIRST so the user knows you heard them. "
        "Without this, voice goes silent while the tool runs — feels like you "
        "stared at the user without responding. The realtime API lets you "
        "speak audio and call a tool in the same response; the audio plays "
        "while the tool runs.\n"
        "\n"
        "### Tools that warrant an ack (slow / network / I/O)\n"
        "- `recall` and other memory or knowledge search tools\n"
        "- MCP and Home Assistant tools (lights, scenes, device status, automations)\n"
        "- Any tool that fetches data over the network or hits an external API\n"
        "- Reminder / schedule / timer creation that writes to the DB\n"
        "- Document or chat-history search\n"
        "- Anything you suspect could take more than ~1 second\n"
        "\n"
        "### Tools that do NOT need an ack (effectively instant)\n"
        "- `switch_voice_app` (context switch, sub-second)\n"
        "- Pure local calculations, current time/date\n"
        "- Trivial state confirmations\n"
        "\n"
        "### Ack phrasing — keep it short, vary it, sound natural\n"
        "Pick something like: \"One moment.\" / \"Let me check on that.\" / "
        "\"Looking that up.\" / \"Give me a sec.\" / \"Checking now.\" / "
        "\"Hang on, let me look.\" / \"On it.\"\n"
        "Vary the phrasing across turns — do not repeat the same ack twice "
        "in a row. Do not apologize or explain — just signal you are working.\n"
        "\n"
        "### Sequence\n"
        "Speak the ack THEN call the tool in the same response. Do not wait "
        "for the tool result before speaking the ack — that defeats the "
        "whole purpose. After the tool result comes back, continue with the "
        "real answer using the data you got.\n"
    )


def build_voice_memory_rules(user_id: str = "", device_info: dict | None = None) -> str:
    """Mandatory-recall-first prompt rules for voice sessions.

    Voice replaces the web chat's automatic per-message retrieval (see
    chat_domain.py:900) with a strong prompt directive telling the model to
    call the `recall` tool on essentially every substantive user turn. This
    keeps memory behavior at parity with web without requiring us to disable
    OpenAI Realtime's auto-response or inject system messages mid-turn.

    The realtime model is generally good at following "ALWAYS do X first"
    instructions, especially when the prompt explains the cost of not doing
    it (answering blind with bad info is worse than ~280ms of tool-call
    latency). We give it concrete query phrasing examples and the small set
    of cases where skipping is acceptable.
    """
    user = (user_id or "").strip().lower()
    if user:
        about_param = f', about="{user}"'
        about_hint = (
            f'- Set `about="{user}"` for first-person questions about the user.'
        )
    else:
        about_param = ""
        about_hint = (
            "- If you don't know who is speaking, ask first, then call recall "
            "with `about` set to that person's lowercase name."
        )

    return (
        "\n## Voice Memory — Mandatory Recall Before Answering\n"
        "**Before you answer ANY user turn that could possibly reference saved "
        "information, you MUST call the `recall` tool first.** Memories in "
        "this system hold critical context — vehicle IDs, account numbers, "
        "family details, preferences, prior decisions, GUIDs for stored "
        "records, etc. — that you cannot guess and that the user expects you "
        "to use.\n"
        "\n"
        "### How to call recall\n"
        "- `query` is the user's literal most recent utterance, lightly "
        f'cleaned. Example: `recall(query="start my truck"{about_param}, max_results=5)`.\n'
        "- Pass the verbatim utterance — semantic similarity is what makes "
        "this work, so paraphrasing or shortening hurts recall quality.\n"
        f"{about_hint}\n"
        "- `max_results=5` is the right default. The backend already ranks "
        "by semantic relevance.\n"
        "\n"
        "### When you may skip recall\n"
        "Only skip when the question is *manifestly* unconnected to anything "
        "the user might have saved:\n"
        "- Pure facts the user couldn't have stored: \"what's 17 times 4\", "
        "\"what time is it\", current weather.\n"
        "- Pure tool actions with no entity reference: \"set a timer for 5 "
        "minutes\", \"turn on the light\" (when the room is already known).\n"
        "- Brand-new greetings: \"hello\", \"good morning\".\n"
        "When in doubt, **call recall**. The latency is small; answering "
        "blind with wrong info is the worse outcome.\n"
        "\n"
        "### How to use the results\n"
        "- If recall returns memories: weave them into your answer directly. "
        "Use any GUIDs, record IDs, or specific values **verbatim** from the "
        "recall output — do not paraphrase IDs.\n"
        "- If recall returns no memories: say you don't have that saved and "
        "ask whether you should remember it now.\n"
        "- Never claim ignorance about something the user has saved without "
        "calling recall first.\n"
    )


def get_default_categories(device_info: dict | None) -> set[str]:
    # The curated voice-core loads for EVERY voice session; home voice devices add theirs.
    # Resolve friendly names ("weather") to their REAL categories ("app:weather") — the same
    # resolution switch_voice_app uses — so the tools actually load (a bare name matches no
    # category and silently loads nothing).
    names = set(VOICE_CORE_CATEGORIES)
    if is_home_voice_device(device_info):
        names |= set(HOME_VOICE_DEFAULT_CATEGORIES)
    return {resolve_app_category(name) or name for name in names}


def is_home_voice_device(device_info: dict | None) -> bool:
    device_info = device_info or {}
    platform = str(device_info.get("platform") or "").lower()
    device_type = str(device_info.get("device_type") or "").lower()
    voice_profile = str(device_info.get("voice_profile") or "").lower()
    return "home_voice" in {platform, device_type, voice_profile}


def normalize_app_name(app_name: str) -> str:
    return (app_name or "").lower().strip().replace("-", "_").replace(" ", "_")


def is_exit_app_name(app_name: str) -> bool:
    app_key = normalize_app_name(app_name)
    return app_key in {"", "base", "exit", "default", "voice", "base_mode"}


def resolve_app_category(app_name: str) -> str | None:
    app_key = normalize_app_name(app_name)
    if app_key.endswith("_app"):
        app_key = app_key[:-4]
    category = LEGACY_APP_ALIASES.get(app_key)
    if category:
        return category

    app_category = discover_app_package_categories().get(app_key)
    if app_category:
        return app_category

    from tool_router import TOOL_CATEGORIES

    direct_category = TOOL_CATEGORIES.get(app_key)
    if direct_category:
        return app_key

    app_prefixed = f"app:{app_key}"
    if app_prefixed in TOOL_CATEGORIES:
        return app_prefixed

    if app_package_exists(app_key):
        return app_key

    for cat_name, cat_info in TOOL_CATEGORIES.items():
        keywords = cat_info.get("keywords", [])
        if app_key in [str(k).lower().replace(" ", "_") for k in keywords]:
            return cat_name
    return None


def build_voice_tools(category_names: Iterable[str] = ()) -> list[dict]:
    """Build Realtime function schemas for voice mode."""
    categories = set(category_names)
    schemas: list[dict] = []
    seen: set[str] = set()

    for schema in get_mcp_tool_schemas_for_categories(categories):
        if schema.get("name") in VOICE_TOOL_EXCLUDE:
            continue
        add_schema(schemas, seen, schema)

    for schema in get_global_tool_schemas():
        if schema.get("name") in VOICE_TOOL_EXCLUDE:
            continue
        add_schema(schemas, seen, schema)

    add_schema(schemas, seen, end_voice_session_schema())
    add_schema(schemas, seen, switch_voice_app_schema())
    add_schema(schemas, seen, enroll_voice_schema())
    return schemas


def get_global_tool_schemas() -> list[dict]:
    from tool_router import TOOL_CATEGORIES
    from mcp_client import mcp_tools
    from local_tools import LOCAL_TOOLS

    global_tool_names = set()
    for cat_name in GLOBAL_CATEGORIES:
        cat_info = TOOL_CATEGORIES.get(cat_name)
        if cat_info:
            global_tool_names.update(cat_info.get("tools", []))

    schemas: list[dict] = []
    seen: set[str] = set()

    for tool in mcp_tools:
        if tool.name in global_tool_names:
            add_schema(schemas, seen, mcp_tool_to_realtime_schema(tool))

    for local_tool in LOCAL_TOOLS:
        add_schema(schemas, seen, local_tool_to_realtime_schema(local_tool))

    return schemas


def get_mcp_tool_schemas_for_categories(category_names: Iterable[str]) -> list[dict]:
    from tool_router import TOOL_CATEGORIES
    from mcp_client import mcp_tools

    tool_names = set()
    for category in category_names:
        cat_info = TOOL_CATEGORIES.get(category)
        if cat_info:
            tool_names.update(cat_info.get("tools", []))
        elif category.startswith("app:"):
            tool_names.update(get_app_tool_names(category.removeprefix("app:")))
        elif app_package_exists(category):
            tool_names.update(get_app_tool_names(category))

    schemas = []
    for tool in mcp_tools:
        if tool.name in tool_names:
            schemas.append(mcp_tool_to_realtime_schema(tool))
    return schemas


def mcp_tool_to_realtime_schema(tool) -> dict:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description or "",
        "parameters": (
            tool.inputSchema
            if getattr(tool, "inputSchema", None)
            else {"type": "object", "properties": {}}
        ),
    }


def local_tool_to_realtime_schema(local_tool: dict) -> dict:
    func = local_tool.get("function", {})
    return {
        "type": "function",
        "name": func.get("name", ""),
        "description": func.get("description", ""),
        "parameters": func.get("parameters", {"type": "object", "properties": {}}),
    }


def add_schema(schemas: list[dict], seen: set[str], schema: dict) -> None:
    name = schema.get("name")
    if not name or name in seen:
        return
    schemas.append(schema)
    seen.add(name)


def end_voice_session_schema() -> dict:
    return {
        "type": "function",
        "name": "end_voice_session",
        "description": (
            "End the current voice session. Use this when the user says goodbye, "
            "'I'm done', 'that's all', 'stop listening', or similar farewell phrases. "
            "Call it silently without speaking first."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    }


def enroll_voice_schema() -> dict:
    return {
        "type": "function",
        "name": "enroll_voice",
        "description": (
            "Register the current speaker's voice so Skipper recognizes who is "
            "talking in future turns. Call this when someone says 'this is <name>', "
            "'I'm <name>', 'learn my voice', or 'remember my voice'. The person's "
            "just-spoken audio is used as the sample — briefly confirm by name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The speaker's name (a household member).",
                },
            },
            "required": ["name"],
        },
    }


def switch_voice_app_schema() -> dict:
    return {
        "type": "function",
        "name": "switch_voice_app",
        "description": (
            "Switch the active app context to load app-specific tools. "
            "Use this when the user says 'open [app]', 'go to [app]', or "
            "'switch to [app]', or when the user's request clearly belongs "
            "to a specific app. For example, investment P&L questions should "
            "switch to investment. Pass 'base' to return to default voice mode. "
            f"Available apps: {available_voice_apps_text()}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": (
                        "The app to switch to, for example 'automation', 'lists', "
                        "'goals', 'reminders', 'home', or 'base'."
                    ),
                }
            },
            "required": ["app_name"],
        },
    }


def load_guide(category: str) -> str | None:
    if category.startswith("app:"):
        app_id = category.removeprefix("app:")
        path = os.path.join(os.path.dirname(__file__), "apps", app_id, "guide.md")
        try:
            with open(path, encoding="utf-8") as f:
                return append_app_guide_context(app_id, f.read())
        except FileNotFoundError:
            return None

    app_guide = os.path.join(os.path.dirname(__file__), "apps", category, "guide.md")
    if os.path.exists(app_guide):
        with open(app_guide, encoding="utf-8") as f:
            return append_app_guide_context(category, f.read())

    path = os.path.join(PROMPTS_DIR, "guides", f"{category}.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def append_app_guide_context(app_id: str, guide_text: str) -> str:
    """Append app-provided dynamic guide context, matching tool_router behavior."""
    try:
        module = importlib.import_module(f"apps.{app_id}.tools")
        context_fn = getattr(module, "get_guide_context", None)
        if callable(context_fn):
            extra = context_fn()
            if extra:
                return guide_text.rstrip() + "\n\n" + str(extra).strip()
    except Exception:
        pass
    return guide_text


def get_app_tool_names(app_id: str) -> set[str]:
    """Return public app tool names for standalone voice category loading."""
    try:
        module = importlib.import_module(f"apps.{app_id}.tools")
    except Exception:
        return set()

    names: set[str] = set()
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if inspect.isfunction(obj) and obj.__doc__:
            names.add(name)
    return names


def app_package_exists(app_id: str) -> bool:
    app_dir = os.path.join(os.path.dirname(__file__), "apps", app_id)
    return os.path.exists(os.path.join(app_dir, "tools.py"))


def load_guides(category_names: Iterable[str]) -> str:
    guides = []
    for category in sorted(set(category_names)):
        guide = load_guide(category)
        if guide:
            guides.append(guide)
    return "\n\n---\n\n".join(guides)
