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
                    "description": "The person's canonical name (lowercase, e.g. 'carol', 'alice')."
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

OPEN_APP_TOOL = {
    "type": "function",
    "function": {
        "name": "open_app",
        "description": "Open a visual app on the user's web desktop. ALWAYS prefer this over printing text when the user says 'show me', 'let me see', 'view', 'browse', 'open', or 'pull up' goals, projects, tasks, notes, documents, recipes, investments/portfolio, reminders, home maintenance/issues, automation, or charts/images. App types: 'goals' (goal/project/task browser), 'documents' (doc list), 'document' (open specific doc by docId), 'recipes' (recipe list/browser), 'recipe' (open specific recipe by recipeId), 'investment' (portfolio dashboard), 'reminders' (reminder manager), 'home' (home hub - maintenance, issues, appliances, insurance, contractors, locator), 'automation' (Home Assistant automation placeholder), 'images' (image gallery list), 'image' (open specific image by imageId - use this IMMEDIATELY after generate_chart with the returned image_id). For 'document', pass docId. For 'recipe', pass recipeId. For 'goals', pass goalId or projectId. For 'image', pass imageId. For 'home', pass tab.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_type": {
                    "type": "string",
                    "enum": ["goals", "documents", "document", "recipes", "recipe", "investment", "reminders", "home", "automation", "locator", "locator-item", "auto", "auto-vehicle", "folders", "folder", "images", "image"],
                    "description": "The app to open. Use 'recipes' for the recipe list, 'recipe' (singular) to open a specific recipe by recipeId. Use 'home' for the home hub (pass tab='issues', 'maintenance', 'appliances', 'insurance', 'contractors', or 'locator'). Use 'automation' for the Home Assistant automation app. Use 'locator' for the item locator list, 'locator-item' to open a specific item by locatorItemId. Use 'auto' for the vehicle list, 'auto-vehicle' to open a specific vehicle by autoVehicleId. Use 'folders' for the folder list, 'folder' to open a specific folder by folderId. Use 'images' for the image gallery list, 'image' to open a specific image by imageId (e.g. after generate_chart)."
                },
                "tab": {
                    "type": "string",
                    "description": "Which tab to open. For investment: 'portfolio', 'rebalance', 'history', 'dashboard'. For home: 'issues' (home issues/problems), 'maintenance' (tasks/reminders), 'appliances', 'insurance', 'contractors', 'locator'."
                },
                "recipeId": {
                    "type": "string",
                    "description": "For app_type='recipe': the recipe ID to open (e.g. 're-abc12345')."
                },
                "docId": {
                    "type": "string",
                    "description": "For app_type='document': the document ID to open (e.g. 'd-abc12345')."
                },
                "locatorItemId": {
                    "type": "string",
                    "description": "For app_type='locator-item': the located item ID to open (e.g. 'loc-abc12345')."
                },
                "autoVehicleId": {
                    "type": "string",
                    "description": "For app_type='auto-vehicle': the vehicle ID to open (e.g. 'veh-abc12345')."
                },
                "folderId": {
                    "type": "string",
                    "description": "For app_type='folder': the folder ID to open (e.g. 'fld-abc12345')."
                },
                "imageId": {
                    "type": "string",
                    "description": "For app_type='image': the image ID to open (e.g. 'i-abc12345'). Use the image_id returned by generate_chart."
                },
                "goalId": {
                    "type": "string",
                    "description": "For app_type='goals': the goal ID to deep-link to (e.g. 'g-abc12345')."
                },
                "projectId": {
                    "type": "string",
                    "description": "For app_type='goals': the project ID to deep-link to (e.g. 'p-abc12345')."
                },
                "taskId": {
                    "type": "string",
                    "description": "For app_type='goals': the task ID to deep-link to (e.g. 't-abc12345')."
                },
                "context": {
                    "type": "object",
                    "description": "Additional context. Usually not needed — use the dedicated params above instead."
                }
            },
            "required": ["app_type"]
        }
    }
}

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
                    "description": "The person's canonical name (lowercase, e.g. 'alice', 'bob'). Must be a known user in the system."
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

LOCAL_TOOLS = [SEND_NOTIFICATION_TOOL, LIST_USERS_TOOL, LIST_ALL_TOOLS_TOOL, REQUEST_TOOLS_TOOL, OPEN_APP_TOOL, READ_FEATURE_SPEC_TOOL, BROADCAST_ANNOUNCEMENT_TOOL, RESTART_AGENT_TOOL]
LOCAL_TOOL_NAMES = {"send_message_to_user", "send_notification", "send_discord_dm", "list_connected_users", "list_all_tools", "request_tools", "open_app", "read_feature_spec", "broadcast_announcement", "restart_agent"}


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
        # The actual tool injection is handled in chat.py's tool loop.
        # This handler returns confirmation + the guide content if available.
        category = tool_args.get("category", "")
        from tool_router import TOOL_CATEGORIES, GUIDES_DIR
        cat = category.lower().strip()
        if cat not in TOOL_CATEGORIES:
            available = ", ".join(TOOL_CATEGORIES.keys())
            return f"Unknown category '{category}'. Available: {available}"
        msg = f"Tools from category '{category}' are now loaded and available. Proceed immediately to use them — do not ask the user for permission."
        # Include the guide content so the agent gets behavioral guidance too
        guide_file = TOOL_CATEGORIES[cat].get("guide")
        if guide_file:
            import os
            guide_path = os.path.join(GUIDES_DIR, guide_file)
            if os.path.exists(guide_path):
                with open(guide_path, "r", encoding="utf-8") as f:
                    guide_content = f.read().strip()
                msg += f"\n\n--- Guide: {guide_file} ---\n{guide_content}"
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

    return f"Unknown local tool: {tool_name}"

