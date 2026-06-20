"""
SkipperBot Local Tools
Tool definitions and handlers that run in agent.py (not via MCP).
These tools need access to runtime state like WebSocket connections or Discord client.
"""

import asyncio

from connections import manager

SEND_MESSAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "send_message_to_user",
        "description": (
            "Deprecated compatibility tool. Use send_notification instead so "
            "Skipper's central notification service can route and log the message."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_user": {
                    "type": "string",
                    "description": "The user_id of the recipient"
                },
                "message": {
                    "type": "string",
                    "description": "The message to send"
                }
            },
            "required": ["to_user", "message"]
        }
    }
}

SEND_NOTIFICATION_TOOL = {
    "type": "function",
    "function": {
        "name": "send_notification",
        "description": (
            "Send a message/notification to a family member through Skipper's "
            "central notification service. Use this when someone asks you to "
            "tell, message, notify, or send something to another person. The "
            "notification service chooses the delivery channel, such as web UI, "
            "mobile push, Discord, or other configured routes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_user": {
                    "type": "string",
                    "description": "The recipient's REAL canonical username (lowercase), exactly as it appears in the system. Do NOT invent, guess, or use a placeholder/example name."
                },
                "message": {
                    "type": "string",
                    "description": "The message to send. Include who it is from when relevant."
                },
                "from_user": {
                    "type": "string",
                    "description": "Optional sender name. Defaults to the current user."
                }
            },
            "required": ["to_user", "message"]
        }
    }
}

LIST_USERS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_connected_users",
        "description": "List all currently connected users.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
}

LIST_ALL_TOOLS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_all_tools",
        "description": "List all available tool categories and their tools. Use this when you need a tool that isn't currently available, or when the user asks what you can do.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
}

REQUEST_TOOLS_TOOL = {
    "type": "function",
    "function": {
        "name": "request_tools",
        "description": "Load a tool category's tools into the current conversation. After calling this, the loaded tools are IMMEDIATELY available — proceed to use them right away without asking the user for permission or confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "The category name to load (e.g. 'filesystem', 'web', 'system', 'utility', 'knowledge', 'messaging')"
                }
            },
            "required": ["category"]
        }
    }
}

# NOTE: open_app's app list is DYNAMIC — never hardcode an enum of app types.
# `build_open_app_tool()` (below) appends the CURRENTLY available apps (installed
# + enabled, reported by the web client) to this description at tool-build time.
# This static dict is the schema/fallback; `app_type` is a free-form string so any
# installed third-party app can be opened. See specs + the memory note.
OPEN_APP_TOOL = {
    "type": "function",
    "function": {
        "name": "open_app",
        "description": (
            "Open a visual app on the user's web desktop. Prefer this over printing "
            "text when the user says 'show me', 'open', 'view', 'pull up', 'let me "
            "see', or 'browse'. Pass the app's `app_type` (an id from the list this "
            "tool provides below), optionally a `tab` to land on a specific view, and "
            "for an item-specific view the entity id (`entity_id`, or a legacy "
            "per-type id like `recipeId`/`docId`)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_type": {
                    "type": "string",
                    "description": "The app id to open — use one of the ids from 'Currently available apps' in this tool's description. Don't invent ids."
                },
                "tab": {
                    "type": "string",
                    "description": "Optional. Which tab/view to open within the app, when it lists tabs (see the per-app tabs in this tool's description)."
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional. The id of a specific item to open in an item view (e.g. a recipe/document/vehicle/image id)."
                },
                "recipeId": {"type": "string", "description": "Legacy deep-link: app_type='recipe', the recipe id (e.g. 're-abc12345')."},
                "docId": {"type": "string", "description": "Legacy deep-link: app_type='document', the document id (e.g. 'd-abc12345')."},
                "locatorItemId": {"type": "string", "description": "Legacy deep-link: app_type='locator-item', the item id (e.g. 'loc-abc12345')."},
                "autoVehicleId": {"type": "string", "description": "Legacy deep-link: app_type='auto-vehicle', the vehicle id (e.g. 'veh-abc12345')."},
                "folderId": {"type": "string", "description": "Legacy deep-link: app_type='folder', the folder id (e.g. 'fld-abc12345')."},
                "imageId": {"type": "string", "description": "Legacy deep-link: app_type='image', the image id (e.g. 'i-abc12345')."},
                "goalId": {"type": "string", "description": "Legacy deep-link: app_type='goals', a goal id (e.g. 'g-abc12345')."},
                "projectId": {"type": "string", "description": "Legacy deep-link: app_type='goals', a project id (e.g. 'p-abc12345')."},
                "taskId": {"type": "string", "description": "Legacy deep-link: app_type='goals', a task id (e.g. 't-abc12345')."},
                "context": {"type": "object", "description": "Optional extra context; usually unnecessary."}
            },
            "required": ["app_type"]
        }
    }
}


# --- Dynamic open_app app catalog (reported by the web client) ----------------
import copy as _copy

_openable_apps_cache: list = []


def set_openable_apps(apps) -> None:
    """Cache the web client's list of openable app-types — dicts of
    {id, name, subview, tabs}. Global: installed+enabled apps are platform-wide,
    and this list intentionally INCLUDES hidden tiles and sub-views (visible only
    means "shows on the desktop"; open_app can still open them)."""
    global _openable_apps_cache
    _openable_apps_cache = [a for a in (apps or []) if isinstance(a, dict) and a.get("id")]


def get_openable_apps() -> list:
    return list(_openable_apps_cache)


def _openable_apps_listing() -> list:
    """Prefer the client-reported registry; before any client reports, fall back
    to the backend's loaded+enabled app ids (so open_app still works at all)."""
    if _openable_apps_cache:
        return _openable_apps_cache
    try:
        from app_platform.loader import get_loaded_apps
        return [{"id": aid, "name": getattr(m, "name", aid), "subview": False, "tabs": []}
                for aid, m in get_loaded_apps().items()]
    except Exception:
        return []


def build_open_app_tool() -> dict:
    """Return OPEN_APP_TOOL with the CURRENTLY available apps appended to its
    description. The list is dynamic (installed + enabled apps) — never hardcoded."""
    primary, subviews = [], []
    for a in sorted(_openable_apps_listing(), key=lambda x: str(x.get("id", ""))):
        tabs = a.get("tabs") or []
        tail = f" (tabs: {', '.join(tabs)})" if tabs else ""
        line = f"  - {a['id']}: {a.get('name', a['id'])}{tail}"
        (subviews if a.get("subview") else primary).append(line)
    listing = "Currently available apps:\n" + ("\n".join(primary) or "  (none reported yet)")
    if subviews:
        listing += "\n  Item views (pass entity_id):\n" + "\n".join(subviews)
    tool = _copy.deepcopy(OPEN_APP_TOOL)
    tool["function"]["description"] = tool["function"]["description"] + "\n\n" + listing
    return tool

READ_FEATURE_SPEC_TOOL = {
    "type": "function",
    "function": {
        "name": "read_feature_spec",
        "description": "Read a feature spec file from the specs/ directory to get context for drafting an announcement. Use this before broadcast_announcement when announcing a new app or major feature that has a spec. Available specs include: TODO, RECIPES, SCHEDULES, SCRUM, EMAIL, LISTS, PRIORITIZE, BRAINSTORMING, INVESTMENT_ANALYST, ITEM_LOCATOR, AUTO_MAINTENANCE, BACKUPS, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "spec_name": {
                    "type": "string",
                    "description": "The spec name (e.g. 'TODO', 'RECIPES'). Will look for specs/<NAME>.md"
                }
            },
            "required": ["spec_name"]
        }
    }
}

BROADCAST_ANNOUNCEMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "broadcast_announcement",
        "description": "Queue an announcement to ALL family members through Skipper's central notification service. CRITICAL: Do NOT call this tool in the same response where you draft the message. You MUST first show the draft in your reply text, then STOP and WAIT for the user to reply with approval (e.g. 'send it', 'looks good'). Only call this tool in a SUBSEQUENT turn after explicit user confirmation. Never draft and send in one turn.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The announcement message to send to everyone. Should be friendly and concise. Include what's new, why it matters, and how to get started."
                },
                "from_user": {
                    "type": "string",
                    "description": "Who is sending this announcement (the person who asked to announce). Will be included in the message attribution."
                }
            },
            "required": ["message"]
        }
    }
}

SEND_DISCORD_DM_TOOL = {
    "type": "function",
    "function": {
        "name": "send_discord_dm",
        "description": (
            "Deprecated compatibility tool. Do not use for new calls; use "
            "send_notification instead so Skipper's central notification service "
            "can route the message intelligently."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_user": {
                    "type": "string",
                    "description": "The recipient's REAL canonical username (lowercase). Must be a known user in the system — never a placeholder or example name."
                },
                "message": {
                    "type": "string",
                    "description": "The message to send. Must clearly state who it is from and that it was sent via Skipper."
                }
            },
            "required": ["to_user", "message"]
        }
    }
}

RESTART_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "restart_agent",
        "description": "Gracefully restart the Skipper agent server. Use when the user says 'restart', 'restart yourself', 'restart the server', 'reboot', etc. Drains in-flight work first (up to 30s), then exits with code 42 so the wrapper script restarts it automatically. Confirm with the user before calling.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
}

GET_PROACTIVE_REPLY_GUIDE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_proactive_reply_guide",
        "description": (
            "Call this when the user appears to be replying to a proactive "
            "message YOU (Skipper) sent on your own initiative — e.g. an "
            "onboarding nudge or a project-management check-in. The conversation "
            "context flags when such a message is pending and which kind it was. "
            "Returns the full guidance for continuing that thread with the right "
            "intent and cadence (don't restart, one step at a time, respect "
            "disengagement). Read it before composing your reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["goal", "pm"],
                    "description": (
                        "The kind of proactive message being replied to, as named "
                        "in the pending-message context: 'goal' (a goal Skipper "
                        "owns / onboarding) or 'pm' (a project-management nudge)."
                    ),
                }
            },
            "required": ["kind"],
        },
    },
}

LOCAL_TOOLS = [SEND_NOTIFICATION_TOOL, LIST_USERS_TOOL, LIST_ALL_TOOLS_TOOL, REQUEST_TOOLS_TOOL, OPEN_APP_TOOL, READ_FEATURE_SPEC_TOOL, BROADCAST_ANNOUNCEMENT_TOOL, RESTART_AGENT_TOOL, GET_PROACTIVE_REPLY_GUIDE_TOOL]
LOCAL_TOOL_NAMES = {"send_message_to_user", "send_notification", "send_discord_dm", "list_connected_users", "list_all_tools", "request_tools", "open_app", "read_feature_spec", "broadcast_announcement", "restart_agent", "get_proactive_reply_guide"}


async def _queue_notification(
    *,
    to_user: str,
    message: str,
    from_user: str = "",
    source_type: str = "message",
) -> str:
    """Create an undelivered notification for the central delivery service."""
    recipient = (to_user or "").lower().strip()
    text = (message or "").strip()
    sender = (from_user or "").lower().strip()

    if not recipient:
        return "Error: to_user is required."
    if not text:
        return "Error: message is required."
    if sender and f"from {sender}" not in text.lower():
        text = f"From {sender.title()} via Skipper: {text}"

    from app_platform.notifications import create_notification

    notif = await asyncio.to_thread(
        create_notification,
        recipient=recipient,
        message=text,
        source_type=source_type,
        source_id="",
        channel="all",
        delivered=False,
    )
    if not notif:
        return f"Error: Could not create notification for '{recipient}'. Is that a known user?"
    return f"Notification queued for {recipient} via Skipper notification service (id: {notif['id']})."


async def handle_local_tool(tool_name: str, tool_args: dict, from_user: str) -> str:
    """Handle tools that run locally in agent.py (not via MCP)."""
    if tool_name == "send_message_to_user":
        return await _queue_notification(
            to_user=tool_args.get("to_user", ""),
            message=tool_args.get("message", ""),
            from_user=from_user,
            source_type="message",
        )

    elif tool_name in {"send_notification", "send_discord_dm"}:
        return await _queue_notification(
            to_user=tool_args.get("to_user", ""),
            message=tool_args.get("message", ""),
            from_user=tool_args.get("from_user") or from_user,
            source_type="message",
        )

    elif tool_name == "list_connected_users":
        users = manager.list_connected_users()
        if users:
            return f"Connected users: {', '.join(users)}"
        return "No users are currently connected."

    elif tool_name == "list_all_tools":
        from tool_router import list_all_tools_text
        return list_all_tools_text()

    elif tool_name == "request_tools":
        # The actual tool injection (adding the category to a slot) is handled in the chat tool
        # loop. This handler returns a DEFINITIVE result so the model never spins:
        #   - category resolves to tools  -> "loaded" + its guide (or "no guide, use descriptions")
        #   - category resolves to NOTHING -> "no such toolset, do NOT retry" + the valid list
        # Validate + fetch via the RESOLVER functions (they read tool_router's CURRENT
        # TOOL_CATEGORIES, which includes app:<id> categories) — NOT a stale imported dict ref.
        category = tool_args.get("category", "")
        from tool_router import get_category_tool_names, get_guides_for_categories, list_categories_text
        cat = category.lower().strip()
        if not get_category_tool_names(cat):
            return (f"There is no '{category}' toolset (it has no tools). Do NOT keep trying to "
                    f"load it — pick a valid category or proceed without one.\n\n{list_categories_text()}")
        msg = (f"Tools from '{category}' are now loaded and available. Proceed immediately to use "
               f"them — do not ask the user for permission.")
        guide = get_guides_for_categories({cat})
        if guide:
            msg += f"\n\n--- Guide for {category} ---\n{guide}"
        else:
            msg += (f"\n\n(No usage guide is registered for '{category}'; rely on the tool "
                    f"descriptions, and do not request this category again.)")
        return msg

    elif tool_name == "open_app":
        app_type = tool_args.get("app_type", "")
        context = tool_args.get("context", {}) or {}
        # Merge top-level 'tab' into context (LLMs handle flat params better than nested)
        tab = tool_args.get("tab", "")
        if tab:
            context["tab"] = tab
        recipe_id = tool_args.get("recipeId", "")
        if recipe_id:
            context["recipeId"] = recipe_id
        doc_id = tool_args.get("docId", "")
        if doc_id:
            context["docId"] = doc_id
        locator_item_id = tool_args.get("locatorItemId", "")
        if locator_item_id:
            context["locatorItemId"] = locator_item_id
        auto_vehicle_id = tool_args.get("autoVehicleId", "")
        if auto_vehicle_id:
            context["autoVehicleId"] = auto_vehicle_id
        folder_id = tool_args.get("folderId", "")
        if folder_id:
            context["folderId"] = folder_id
        image_id = tool_args.get("imageId", "")
        if image_id:
            context["imageId"] = image_id
        goal_id = tool_args.get("goalId", "")
        if goal_id:
            context["goalId"] = goal_id
        project_id = tool_args.get("projectId", "")
        if project_id:
            context["projectId"] = project_id
        task_id = tool_args.get("taskId", "")
        if task_id:
            context["taskId"] = task_id
        entity_id = tool_args.get("entity_id", "")
        if entity_id:
            context["entity_id"] = entity_id
        sent = await manager.send_to_user(from_user, {
            "type": "open_app",
            "app_type": app_type,
            "context": context,
        })
        if sent:
            return f"Opened {app_type} app on the user's desktop."
        return f"User '{from_user}' is not connected via web. The app can only be opened on the web interface."

    elif tool_name == "read_feature_spec":
        import os
        spec_name = tool_args.get("spec_name", "").strip().upper()
        spec_path = os.path.join("specs", f"{spec_name}.md")
        if not os.path.exists(spec_path):
            available = [f.replace('.md', '') for f in os.listdir("specs") if f.endswith('.md')]
            return f"Spec '{spec_name}' not found. Available: {', '.join(sorted(available))}"
        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Truncate if very long — LLM just needs the overview + feature list
        if len(content) > 6000:
            content = content[:6000] + "\n\n[... truncated ...]"
        return f"## Spec: {spec_name}\n\n{content}"

    elif tool_name == "broadcast_announcement":
        message = tool_args.get("message", "").strip()
        if not message:
            return "Error: message is required."
        sender = tool_args.get("from_user", from_user) or from_user

        from data_layer.users import get_human_users

        all_users = await asyncio.to_thread(get_human_users)
        results = []

        for user in all_users:
            name = user["name"]
            result = await _queue_notification(
                to_user=name,
                message=message,
                from_user=sender,
                source_type="announcement",
            )
            results.append(f"{name}: {result}")

        return f"Announcement queued for {len(all_users)} family members.\n" + "\n".join(results)

    elif tool_name == "restart_agent":
        from thinking_scheduler import request_shutdown as thinking_shutdown, is_shutting_down
        from app_platform.jobs import request_shutdown as jobs_shutdown
        from apps.reminders.scheduler import request_shutdown as reminders_shutdown
        import asyncio as _asyncio

        if is_shutting_down():
            return "Agent is already shutting down."

        thinking_shutdown()
        jobs_shutdown()
        reminders_shutdown()

        await manager.broadcast({"type": "server_restarting"})

        # Import and schedule the drain-and-exit task
        from agent import _drain_and_exit
        _asyncio.create_task(_drain_and_exit(max_wait=30))

        return "Restarting — draining in-flight work (up to 30s) then restarting. The page will reconnect automatically."

    elif tool_name == "get_proactive_reply_guide":
        # Full continuity guidance for a reply to a proactive DM. Shared source
        # of truth with the thinking domains — see apps/goals/prompts/
        # proactive_reply_guide.md and specs/PROACTIVE_MESSAGING.md.
        from apps.goals.data import load_proactive_reply_guide
        guide = await asyncio.to_thread(load_proactive_reply_guide, tool_args.get("kind", ""))
        return guide or (
            "No additional guidance available — continue the thread naturally "
            "without restarting, one step at a time."
        )

    return f"Unknown local tool: {tool_name}"

