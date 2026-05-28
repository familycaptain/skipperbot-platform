"""
SkipperBot MCP Server
Model Context Protocol server using FastMCP for tool integration.
Tools are imported from the tools/ folder - one tool per file.
"""

import inspect
import sys
import os
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr, sys.stdin):
        if _stream and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import logging
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

from tools.time_tool import get_current_time
from tools.calculator_tool import calculate
from tools.echo_tool import echo
from tools.tool_creator import create_tool, update_tool, list_tool_files, read_tool, delete_tool
from tools.tool_registry import register_tool, unregister_tool
from tools.mcp_control import restart_mcp_server, start_mcp_server, stop_mcp_server, mcp_server_status
from tools.zip_weather_tool import (
    get_current_weather_by_zip,
    get_rain_chance_by_zip,
    get_hourly_forecast_by_zip,
)
from tools.glob_search_tool import glob_search
from tools.tool_guide_tool import get_tool_creation_guide
from tools.memory_tool import remember, recall, forget
from tools.knowledge_tool import learn_from_url, query_knowledge, list_knowledge_sources, remove_knowledge_source, list_knowledge_crawls, get_knowledge_crawl
from tools.chatlog_tool import search_chat_history, list_chat_users
from tools.ping_tool import ping_host
from tools.grep_tool import grep_search
from tools.curl_tool import curl_request
from tools.os_find_tool import os_level_find
from tools.cat_tool import cat_file
from tools.ls_tool import ls_dir
from tools.tail_tool import tail_file
from tools.json_validate_tool import json_validate_file
from tools.yaml_validate_tool import yaml_validate_file
from tools.pushover_tool import send_pushover_notification
from tools.reminder_tool import set_reminder, get_reminders, cancel_reminder_by_id, modify_reminder_by_id, set_nag, snooze_reminder
from tools.timer_tool import start_timer, list_timers, cancel_timer
from tools.link_tool import link_entities, get_entity_links, unlink_entities
from tools.notification_tool import get_recent_notifications
from tools.artifact_tool import attach_artifact, read_artifact, list_entity_artifacts, delete_artifact_by_id, update_artifact
from tools.job_tool import create_job, get_jobs, update_job, run_job
from tools.list_tool import (
    create_list, show_list, show_all_lists, add_list_item, remove_list_item,
    move_list_items, sync_list, trello_show_board, trello_add_card,
    trello_move_card, trello_archive_card, trello_list_boards,
    trello_suggest_list,
    trello_get_card, trello_update_card, trello_card_checklist,
    trello_add_comment, trello_card_labels, trello_board_labels,
    connect_trello_board, disconnect_trello_board, set_list_aliases,
    set_item_tracking,
    get_todo_list, add_todo_item, mark_todo_done,
)
from tools.internet_search_tool import internet_search
from tools.git_tool import git_tool
from tools.guide_tool import get_guide
from tools.doc_tool import create_doc, get_doc, update_doc, append_to_doc, search_docs, list_docs, update_doc_meta, delete_doc, enhance_doc
from tools.research_tool import start_research, check_research, cancel_research, list_research_jobs, refine_research
from tools.print_tool import print_doc
from tools.prioritize_tool import list_focus, promote_focus, clear_focus, get_backlog_summary, get_family_focus
from tools.brainstorming_tool import create_idea, list_ideas, search_ideas, get_idea, update_idea, delete_idea, graduate_idea, update_idea_document, append_to_idea_document, read_idea_document, revise_idea_document
from tools.scrum_tool import respond_to_scrum_item, get_pending_scrum_items
from tools.skipper_email_tool import check_skipper_inbox, read_skipper_email, send_skipper_email, search_skipper_email
from tools.folder_tool import create_folder, get_folder, list_folders, add_to_folder, create_doc_in_folder, remove_from_folder, move_to_folder, delete_folder, restore_folder, search_folders
from tools.behavior_tool import add_behavior, list_behaviors, update_behavior, remove_behavior, toggle_behavior
# Homeopathy tools moved to apps/homeopathy/tools.py (app package)

mcp = FastMCP("SkipperBot Tools")

mcp.tool()(get_current_time)
mcp.tool()(calculate)
mcp.tool()(echo)
mcp.tool()(create_tool)
mcp.tool()(update_tool)
mcp.tool()(list_tool_files)
mcp.tool()(read_tool)
mcp.tool()(delete_tool)
mcp.tool()(register_tool)
mcp.tool()(unregister_tool)
mcp.tool()(restart_mcp_server)
mcp.tool()(start_mcp_server)
mcp.tool()(stop_mcp_server)
mcp.tool()(mcp_server_status)
mcp.tool()(get_current_weather_by_zip)
mcp.tool()(get_rain_chance_by_zip)
mcp.tool()(get_hourly_forecast_by_zip)
mcp.tool()(glob_search)
mcp.tool()(get_tool_creation_guide)
mcp.tool()(remember)
mcp.tool()(recall)
mcp.tool()(forget)
mcp.tool()(learn_from_url)
mcp.tool()(query_knowledge)
mcp.tool()(list_knowledge_sources)
mcp.tool()(remove_knowledge_source)
mcp.tool()(list_knowledge_crawls)
mcp.tool()(get_knowledge_crawl)
mcp.tool()(search_chat_history)
mcp.tool()(list_chat_users)
mcp.tool()(ping_host)
mcp.tool()(grep_search)
mcp.tool()(curl_request)
mcp.tool()(os_level_find)
mcp.tool()(cat_file)
mcp.tool()(ls_dir)
mcp.tool()(tail_file)
mcp.tool()(json_validate_file)
mcp.tool()(yaml_validate_file)
mcp.tool()(send_pushover_notification)
mcp.tool()(set_reminder)
mcp.tool()(get_reminders)
mcp.tool()(cancel_reminder_by_id)
mcp.tool()(modify_reminder_by_id)
mcp.tool()(set_nag)
mcp.tool()(snooze_reminder)
mcp.tool()(start_timer)
mcp.tool()(list_timers)
mcp.tool()(cancel_timer)
mcp.tool()(create_list)
mcp.tool()(show_list)
mcp.tool()(show_all_lists)
mcp.tool()(add_list_item)
mcp.tool()(remove_list_item)
mcp.tool()(move_list_items)
mcp.tool()(sync_list)
mcp.tool()(trello_show_board)
mcp.tool()(trello_add_card)
mcp.tool()(trello_move_card)
mcp.tool()(trello_archive_card)
mcp.tool()(trello_list_boards)
mcp.tool()(trello_suggest_list)
mcp.tool()(trello_get_card)
mcp.tool()(trello_update_card)
mcp.tool()(trello_card_checklist)
mcp.tool()(trello_add_comment)
mcp.tool()(trello_card_labels)
mcp.tool()(trello_board_labels)
mcp.tool()(connect_trello_board)
mcp.tool()(disconnect_trello_board)
mcp.tool()(set_list_aliases)
mcp.tool()(set_item_tracking)
mcp.tool()(get_todo_list)
mcp.tool()(add_todo_item)
mcp.tool()(mark_todo_done)
mcp.tool()(link_entities)
mcp.tool()(get_entity_links)
mcp.tool()(unlink_entities)
mcp.tool()(get_recent_notifications)
mcp.tool()(attach_artifact)
mcp.tool()(read_artifact)
mcp.tool()(list_entity_artifacts)
mcp.tool()(update_artifact)
mcp.tool()(delete_artifact_by_id)
mcp.tool()(create_job)
mcp.tool()(get_jobs)
mcp.tool()(update_job)
mcp.tool()(run_job)
mcp.tool()(internet_search)
mcp.tool()(git_tool)
mcp.tool()(get_guide)
mcp.tool()(create_doc)
mcp.tool()(get_doc)
mcp.tool()(update_doc)
mcp.tool()(append_to_doc)
mcp.tool()(search_docs)
mcp.tool()(list_docs)
mcp.tool()(update_doc_meta)
mcp.tool()(delete_doc)
mcp.tool()(enhance_doc)
mcp.tool()(start_research)
mcp.tool()(check_research)
mcp.tool()(cancel_research)
mcp.tool()(list_research_jobs)
mcp.tool()(refine_research)
mcp.tool()(print_doc)
# Homeopathy tools auto-registered from apps/homeopathy/tools.py
mcp.tool()(list_focus)
mcp.tool()(promote_focus)
mcp.tool()(clear_focus)
mcp.tool()(get_backlog_summary)
mcp.tool()(get_family_focus)
mcp.tool()(create_idea)
mcp.tool()(list_ideas)
mcp.tool()(search_ideas)
mcp.tool()(get_idea)
mcp.tool()(update_idea)
mcp.tool()(delete_idea)
mcp.tool()(graduate_idea)
mcp.tool()(update_idea_document)
mcp.tool()(append_to_idea_document)
mcp.tool()(read_idea_document)
mcp.tool()(revise_idea_document)
mcp.tool()(respond_to_scrum_item)
mcp.tool()(get_pending_scrum_items)
mcp.tool()(check_skipper_inbox)
mcp.tool()(read_skipper_email)
mcp.tool()(send_skipper_email)
mcp.tool()(search_skipper_email)
mcp.tool()(create_folder)
mcp.tool()(get_folder)
mcp.tool()(list_folders)
mcp.tool()(add_to_folder)
mcp.tool()(create_doc_in_folder)
mcp.tool()(remove_from_folder)
mcp.tool()(move_to_folder)
mcp.tool()(delete_folder)
mcp.tool()(restore_folder)
mcp.tool()(search_folders)
mcp.tool()(add_behavior)
mcp.tool()(list_behaviors)
mcp.tool()(update_behavior)
mcp.tool()(remove_behavior)
mcp.tool()(toggle_behavior)


# ---------------------------------------------------------------------------
# Auto-discover and register tools from app packages in apps/
# ---------------------------------------------------------------------------

def _register_app_tools():
    """Discover app packages and register their tool functions with MCP."""
    import importlib.util
    from pathlib import Path

    apps_dir = Path(__file__).parent / "apps"
    if not apps_dir.is_dir():
        return

    for child in sorted(apps_dir.iterdir()):
        if not child.is_dir():
            continue
        tools_path = child / "tools.py"
        manifest_path = child / "manifest.yaml"
        if not tools_path.exists() or not manifest_path.exists():
            continue

        app_id = child.name
        module_name = f"apps.{app_id}.tools"

        try:
            spec = importlib.util.spec_from_file_location(module_name, tools_path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            count = 0
            for name in dir(module):
                if name.startswith("_"):
                    continue
                obj = getattr(module, name)
                if callable(obj) and inspect.isfunction(obj) and obj.__doc__:
                    mcp.tool()(obj)
                    count += 1

            if count:
                logger.info("MCP: Registered %d tool(s) from app '%s'", count, app_id)
        except Exception as e:
            logger.error("MCP: Failed to load tools from app '%s': %s", app_id, e)


_register_app_tools()


if __name__ == "__main__":
    mcp.run()
