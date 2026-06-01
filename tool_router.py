"""
SkipperBot Tool Router
Category-based tool selection to minimize token usage per turn.
Only injects relevant tool schemas based on message keywords.
Core tools are always available; others injected on demand.

All categories and tool assignments are stored in tool_routes.json.
"""

import json
import os
import re

# ---------------------------------------------------------------------------
# Tool categories come from THREE layers, merged into TOOL_CATEGORIES:
#   1. base  — tool_routes.json (git-tracked, READ-ONLY at runtime): the
#              canonical built-in categories. Deploys (git pull) update this.
#   2. local — tool_routes.local.json (GITIGNORED): routes registered at
#              runtime (create_tool / register_tool_route / acks). Written by
#              _save_routes; never tracked, so it can't collide with git pull.
#   3. app   — in-memory `app:<id>` categories from loaded app packages
#              (merge_app_tool_routes); rebuilt every boot, never persisted.
#
# Keeping runtime writes OUT of the tracked file is the durable fix for deploys
# corrupting routing: tool_routes.json used to be tracked AND written at
# runtime, so a deploy's merge left conflict markers → unparseable JSON →
# every category silently dropped.
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROUTES_FILE = os.path.join(BASE_DIR, "tool_routes.json")
LOCAL_ROUTES_FILE = os.path.join(BASE_DIR, "tool_routes.local.json")
GUIDES_DIR = os.path.join(BASE_DIR, "prompts", "guides")

TOOL_CATEGORIES: dict = {}
_BASE_ROUTES: dict = {}
_LOCAL_ROUTES: dict = {}
_APP_ROUTES: dict = {}


def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _blank_category() -> dict:
    return {"description": "", "tools": [], "keywords": [], "ack": {}}


def _merge_category(dst: dict, src: dict) -> None:
    """Overlay src onto dst in place: union tools/keywords, merge acks."""
    if src.get("description") and not dst.get("description"):
        dst["description"] = src["description"]
    for tool in src.get("tools", []) or []:
        if tool not in dst["tools"]:
            dst["tools"].append(tool)
    for kw in src.get("keywords", []) or []:
        if kw not in dst["keywords"]:
            dst["keywords"].append(kw)
    ack = src.get("ack")
    if isinstance(ack, dict):
        dst["ack"].update(ack)
    for extra in ("_guide_path", "guide"):
        if src.get(extra) and not dst.get(extra):
            dst[extra] = src[extra]


def _rebuild_categories():
    """Rebuild TOOL_CATEGORIES = base ← local ← app, then refresh the lookup."""
    global TOOL_CATEGORIES
    merged: dict = {}
    for layer in (_BASE_ROUTES, _LOCAL_ROUTES, _APP_ROUTES):
        for name, info in layer.items():
            if not isinstance(info, dict):
                continue
            _merge_category(merged.setdefault(name, _blank_category()), info)
    TOOL_CATEGORIES = merged
    _rebuild_lookup()


def _load_routes():
    """(Re)load the base + local route layers from disk and rebuild categories.

    App-package routes (_APP_ROUTES) are preserved across reloads so picking up
    new MCP tools after a restart doesn't drop the loaded apps' categories.
    """
    global _BASE_ROUTES, _LOCAL_ROUTES
    _BASE_ROUTES = _read_json(ROUTES_FILE)
    _LOCAL_ROUTES = _read_json(LOCAL_ROUTES_FILE)
    _rebuild_categories()


def _save_routes():
    """Persist ONLY the runtime/local layer to the gitignored overlay file.

    The tracked tool_routes.json is never written at runtime — that's what
    keeps deploys (git pull) from ever conflicting on it.
    """
    with open(LOCAL_ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump(_LOCAL_ROUTES, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def reload_routes():
    """Reload categories from tool_routes.json and rebuild lookup.

    Call this after the MCP server process has registered new tools,
    so the agent process picks up the changes.
    """
    _load_routes()


# Build a flat lookup: tool_name → category
def _rebuild_lookup():
    global TOOL_TO_CATEGORY
    TOOL_TO_CATEGORY = {}
    for cat_name, cat_info in TOOL_CATEGORIES.items():
        for tool_name in cat_info["tools"]:
            TOOL_TO_CATEGORY[tool_name] = cat_name


TOOL_TO_CATEGORY = {}
# Load on import (now that _rebuild_lookup is defined): builds base ← local.
_load_routes()

# Meta-tool names (always injected as LOCAL_TOOLS, handled separately)
META_TOOL_NAMES = {"list_all_tools", "request_tools", "open_app", "restart_agent"}


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

_RANK_REF_RE = re.compile(r'\b[gpt]\d+\b', re.IGNORECASE)

# Keyword matching uses word-boundary regex, not raw substring containment.
# This avoids false positives like "at" matching inside "what"/"weather", or
# "ha" matching inside "what". We only add \b on a side of the keyword that
# begins/ends with a word character — keywords with leading or trailing
# punctuation (e.g. "% chance of rain") get no boundary on that side, since
# \b only fires at a word/non-word transition.
_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _keyword_pattern(keyword: str) -> re.Pattern:
    pat = _KEYWORD_PATTERN_CACHE.get(keyword)
    if pat is not None:
        return pat
    parts: list[str] = []
    first = keyword[:1]
    last = keyword[-1:]
    if first.isalnum() or first == "_":
        parts.append(r"\b")
    parts.append(re.escape(keyword))
    if last.isalnum() or last == "_":
        parts.append(r"\b")
    pat = re.compile("".join(parts))
    _KEYWORD_PATTERN_CACHE[keyword] = pat
    return pat


def _match_categories(message: str) -> set[str]:
    """Determine which tool categories are relevant to a message."""
    return set(_match_categories_with_reasons(message).keys())


def _match_categories_with_reasons(message: str) -> dict[str, list[str]]:
    """Return matched categories with the keywords that triggered each match.

    Returned dict shape: ``{category_name: [matched_keyword, ...]}``.
    The "core" category is always included with an empty keyword list since
    it is unconditional. Matching uses word-boundary regex so short keywords
    like ``at`` and ``ha`` don't fire inside ``what``/``weather``.
    """
    msg_lower = message.lower()
    matched: dict[str, list[str]] = {"core": []}

    # Rank references (G3, P1, T5) always route to goals
    rank_match = _RANK_REF_RE.search(msg_lower)
    if rank_match:
        matched.setdefault("goals", []).append(f"rank-ref:{rank_match.group(0)}")

    for cat_name, cat_info in TOOL_CATEGORIES.items():
        if cat_name == "core":
            continue
        hits: list[str] = []
        for keyword in cat_info["keywords"]:
            if not keyword:
                continue
            if _keyword_pattern(keyword).search(msg_lower):
                hits.append(keyword)
        if hits:
            matched.setdefault(cat_name, []).extend(hits)

    return matched


def get_match_debug_for_message(
    message: str,
    extra_categories: set[str] | None = None,
) -> list[dict]:
    """Return per-category debug data for a message.

    Each entry: ``{"category": str, "keywords_hit": [str, ...], "guide": str|None,
    "tools": [str, ...], "source": "keyword"|"core"|"extra_category"|"rank_ref"}``.

    "extra_category" entries come from callers that force-included a category
    (e.g. dynamic ``request_tools``, app context, voice device defaults) — they
    are *not* keyword-driven, and we record them so the audit trail explains
    every category that ended up routed.
    """
    reasons = _match_categories_with_reasons(message)
    extras = extra_categories or set()
    debug: list[dict] = []

    seen: set[str] = set()
    for cat_name, hits in reasons.items():
        cat_info = TOOL_CATEGORIES.get(cat_name) or {}
        if cat_name == "core":
            source = "core"
        elif any(h.startswith("rank-ref:") for h in hits):
            source = "rank_ref"
        else:
            source = "keyword"
        debug.append({
            "category": cat_name,
            "keywords_hit": hits,
            "guide": cat_info.get("guide") or (
                "<app-package>" if cat_info.get("_guide_path") else None
            ),
            "tools": list(cat_info.get("tools", [])),
            "source": source,
        })
        seen.add(cat_name)

    for cat_name in sorted(extras):
        if cat_name in seen:
            continue
        cat_info = TOOL_CATEGORIES.get(cat_name) or {}
        debug.append({
            "category": cat_name,
            "keywords_hit": [],
            "guide": cat_info.get("guide") or (
                "<app-package>" if cat_info.get("_guide_path") else None
            ),
            "tools": list(cat_info.get("tools", [])),
            "source": "extra_category",
        })

    return debug


def get_tools_for_message(message: str, extra_categories: set[str] | None = None) -> set[str]:
    """Return the set of tool names that should be available for this message.

    Args:
        message: The user's message text.
        extra_categories: Additional categories to include (e.g. from request_tools).

    Returns:
        Set of tool names to include in the OpenAI call.
    """
    categories = _match_categories(message)
    if extra_categories:
        categories |= extra_categories

    tool_names = set()
    for cat_name in categories:
        cat_info = TOOL_CATEGORIES.get(cat_name)
        if cat_info:
            tool_names.update(cat_info["tools"])

    return tool_names


def get_guides_for_message(message: str, extra_categories: set[str] | None = None) -> str:
    """Return concatenated guide content for categories matched by this message.

    Reads guide files from prompts/guides/ based on the "guide" field in each
    matched category of tool_routes.json.

    Returns:
        Combined guide text to inject into the system prompt, or empty string.
    """
    categories = _match_categories(message)
    if extra_categories:
        categories |= extra_categories

    guides = []
    seen: set[str] = set()
    for cat_name in sorted(categories):
        cat_info = TOOL_CATEGORIES.get(cat_name)
        if not cat_info:
            continue
        # App packages use _guide_path (absolute), legacy uses guide (relative)
        guide_path = cat_info.get("_guide_path")
        guide_file = cat_info.get("guide")
        if guide_path:
            if guide_path not in seen and os.path.exists(guide_path):
                seen.add(guide_path)
                try:
                    with open(guide_path, "r", encoding="utf-8") as f:
                        guide_text = f.read().strip()
                    context_fn = cat_info.get("_guide_context_fn")
                    if context_fn:
                        try:
                            extra = context_fn()
                            if extra:
                                guide_text += "\n\n" + extra.strip()
                        except Exception:
                            pass
                    guides.append(guide_text)
                except OSError:
                    pass
        elif guide_file:
            if guide_file not in seen:
                seen.add(guide_file)
                filepath = os.path.join(GUIDES_DIR, guide_file)
                if os.path.exists(filepath):
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            guides.append(f.read().strip())
                    except OSError:
                        pass

    if guides:
        return "\n\n---\n\n".join(guides)
    return ""


# ---------------------------------------------------------------------------
# Meta-tool helpers
# ---------------------------------------------------------------------------

def list_all_tools_text() -> str:
    """Return a formatted listing of all tool categories and their tools."""
    lines = ["Available tool categories:\n"]
    for cat_name, cat_info in TOOL_CATEGORIES.items():
        if cat_name == "core":
            lines.append(f"  {cat_name} (always available): {cat_info['description']}")
        else:
            lines.append(f"  {cat_name}: {cat_info['description']}")
        for tool_name in cat_info["tools"]:
            lines.append(f"    - {tool_name}")
    lines.append("\nUse request_tools(category) to load a category's tools into this conversation.")
    return "\n".join(lines)


def get_category_tool_names(category: str) -> set[str]:
    """Get all tool names for a given category."""
    cat_info = TOOL_CATEGORIES.get(category.lower().strip())
    if not cat_info:
        return set()
    return set(cat_info["tools"])


def get_tools_for_categories(categories: set[str]) -> set[str]:
    """Return the union of tool names for the given category names.

    Used by the thinking loop to load tools by domain config instead of
    keyword matching.
    """
    tool_names: set[str] = set()
    for cat_name in categories:
        cat_info = TOOL_CATEGORIES.get(cat_name.lower().strip())
        if cat_info:
            tool_names.update(cat_info["tools"])
    return tool_names


def get_guides_for_categories(categories: set[str]) -> str:
    """Return concatenated guide content for the given category names.

    Like get_guides_for_message() but takes explicit categories instead
    of keyword-matching a message. Used by the thinking loop.
    """
    guides = []
    seen: set[str] = set()
    for cat_name in sorted(categories):
        cat_info = TOOL_CATEGORIES.get(cat_name.lower().strip())
        if not cat_info:
            continue
        # App packages use _guide_path (absolute), legacy uses guide (relative)
        guide_path = cat_info.get("_guide_path")
        guide_file = cat_info.get("guide")
        if guide_path:
            if guide_path not in seen and os.path.exists(guide_path):
                seen.add(guide_path)
                try:
                    with open(guide_path, "r", encoding="utf-8") as f:
                        guide_text = f.read().strip()
                    context_fn = cat_info.get("_guide_context_fn")
                    if context_fn:
                        try:
                            extra = context_fn()
                            if extra:
                                guide_text += "\n\n" + extra.strip()
                        except Exception:
                            pass
                    guides.append(guide_text)
                except OSError:
                    pass
        elif guide_file:
            if guide_file not in seen:
                seen.add(guide_file)
                filepath = os.path.join(GUIDES_DIR, guide_file)
                if os.path.exists(filepath):
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            guides.append(f.read().strip())
                    except OSError:
                        pass

    if guides:
        return "\n\n---\n\n".join(guides)
    return ""


def get_ack_template(tool_name: str, tool_args: dict) -> str | None:
    """Look up an ack template for a tool from tool_routes.json.

    Supports variant keys like ``tool_name:flag`` — if the flag arg is
    truthy, the variant template is preferred over the base one.

    Returns the template string with ``{arg}`` placeholders filled in from
    *tool_args*, or ``None`` if no ack is configured for this tool.
    """
    for cat_info in TOOL_CATEGORIES.values():
        ack_map = cat_info.get("ack")
        if not ack_map:
            continue

        # Check for variant keys first (e.g. learn_from_url:follow_links)
        template = None
        for key, tmpl in ack_map.items():
            if ":" in key:
                base, flag = key.split(":", 1)
                if base == tool_name and tool_args.get(flag):
                    template = tmpl
                    break

        # Fall back to base key
        if template is None:
            template = ack_map.get(tool_name)

        if template is not None:
            try:
                return template.format_map(tool_args)
            except (KeyError, IndexError):
                return template  # return raw template if args don't match
    return None


# ---------------------------------------------------------------------------
# Dynamic registration (called by tool_registry.py)
# ---------------------------------------------------------------------------

def register_tool_route(
    tool_name: str,
    category: str,
    keywords: list[str] | None = None
) -> str:
    """Register a tool into a category. Updates in-memory state and persists to JSON.

    Args:
        tool_name: The function name of the tool.
        category: Category to add it to (must already exist).
        keywords: Optional extra keywords to add to the category.

    Returns:
        Status message.
    """
    category = category.lower().strip()

    if category not in TOOL_CATEGORIES:
        return f"Error: Category '{category}' does not exist. Use create_category first."

    # Write into the local (gitignored) overlay, not the tracked base file.
    local = _LOCAL_ROUTES.setdefault(category, {"tools": [], "keywords": [], "ack": {}})
    local.setdefault("tools", [])
    local.setdefault("keywords", [])
    if tool_name not in TOOL_CATEGORIES[category].get("tools", []) and tool_name not in local["tools"]:
        local["tools"].append(tool_name)
    if keywords:
        existing_kw = set(TOOL_CATEGORIES[category].get("keywords", []))
        for kw in keywords:
            k = kw.lower()
            if k not in existing_kw and k not in local["keywords"]:
                local["keywords"].append(k)

    _rebuild_categories()
    _save_routes()

    return f"Tool '{tool_name}' registered in category '{category}'."


def create_category(
    name: str,
    description: str,
    keywords: list[str]
) -> str:
    """Create a new tool category.

    Args:
        name: Category name (lowercase, no spaces).
        description: Short description of what tools in this category do.
        keywords: List of keywords that trigger this category.

    Returns:
        Status message.
    """
    name = name.lower().strip()

    if name in TOOL_CATEGORIES:
        return f"Category '{name}' already exists."

    _LOCAL_ROUTES[name] = {
        "description": description,
        "tools": [],
        "keywords": [kw.lower() for kw in keywords],
        "ack": {},
    }
    _rebuild_categories()
    _save_routes()

    return f"Category '{name}' created with keywords: {keywords}"


def unregister_tool_route(tool_name: str) -> str:
    """Remove a runtime-registered tool from the local overlay categories.

    Only routes in the local (gitignored) layer can be removed — built-in
    routes from the tracked base file are permanent at runtime.
    """
    removed_from = []
    for cat_name, cat_info in _LOCAL_ROUTES.items():
        tools = cat_info.get("tools", [])
        if tool_name in tools:
            tools.remove(tool_name)
            removed_from.append(cat_name)
        ack = cat_info.get("ack")
        if isinstance(ack, dict):
            ack.pop(tool_name, None)

    _rebuild_categories()
    _save_routes()

    if removed_from:
        return f"Tool '{tool_name}' removed from categories: {', '.join(removed_from)}"
    if tool_name in TOOL_TO_CATEGORY:
        return (f"Tool '{tool_name}' is a built-in route (category "
                f"'{TOOL_TO_CATEGORY[tool_name]}') and can't be unregistered at runtime.")
    return f"Tool '{tool_name}' was not in any category."


def set_local_ack(category: str, tool_name: str, ack_template: str) -> str:
    """Persist an ack template for a tool into the local (gitignored) overlay.

    Used by the tool registry when create_tool adds a tool, so acks are never
    written into the tracked tool_routes.json.
    """
    category = category.lower().strip()
    if category not in TOOL_CATEGORIES:
        return f"Warning: category '{category}' not in tool routes — ack not added."
    local = _LOCAL_ROUTES.setdefault(category, {"tools": [], "keywords": [], "ack": {}})
    local.setdefault("ack", {})[tool_name] = ack_template
    _rebuild_categories()
    _save_routes()
    return f"Added ack for {tool_name}: \"{ack_template}\""


def list_categories_text() -> str:
    """Return a compact list of category names and descriptions."""
    lines = []
    for name, info in TOOL_CATEGORIES.items():
        lines.append(f"  {name}: {info['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# App package integration
# ---------------------------------------------------------------------------

def merge_app_tool_routes(app_routes: dict[str, dict]):
    """Merge tool routes from loaded app packages into TOOL_CATEGORIES.

    Called by the app loader after all apps are loaded. Each entry is a
    tool_routes-compatible dict with 'description', 'tools', 'keywords',
    and optionally 'guide_path' (absolute path to the app's guide.md).

    App routes are keyed by app_id and prefixed with 'app:' to avoid
    collisions with legacy categories. They live in the in-memory _APP_ROUTES
    layer (never persisted), so reloading the on-disk layers can't drop them.
    """
    for app_id, route_info in app_routes.items():
        cat_name = f"app:{app_id}"

        entry = {
            "description": route_info.get("description", ""),
            "tools": list(route_info.get("tools", [])),
            "ack": dict(route_info.get("ack", {})),
            "keywords": list(route_info.get("keywords", [])),
        }

        # Store guide_path for the guide loader (not standard tool_routes field)
        guide_path = route_info.get("guide_path")
        if guide_path:
            entry["_guide_path"] = guide_path

        _APP_ROUTES[cat_name] = entry

    _rebuild_categories()
