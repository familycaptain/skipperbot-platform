"""
SkipperBot Tools
Import all tools here to register them with the MCP server.
"""

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
from tools.ping_tool import ping_host
from tools.grep_tool import grep_search
from tools.curl_tool import curl_request
from tools.knowledge_tool import learn_from_url, query_knowledge, list_knowledge_sources, remove_knowledge_source
from tools.chatlog_tool import search_chat_history, list_chat_users
from tools.os_find_tool import os_level_find
from tools.cat_tool import cat_file
from tools.ls_tool import ls_dir
from tools.tail_tool import tail_file
from tools.json_validate_tool import json_validate_file
from tools.yaml_validate_tool import yaml_validate_file
from tools.pushover_tool import send_pushover_notification
from tools.reminder_tool import set_reminder, get_reminders, cancel_reminder_by_id, modify_reminder_by_id, set_nag, snooze_reminder
from apps.goals.tools import create_goal, create_project, create_task, update_item, get_goals_summary, get_goal_detail, get_project_detail, get_entity_detail, get_my_tasks, search_goals, update_entity_notes, get_entity_notes, set_due_reminder, delete_item, set_task_order, set_task_dependency, enable_project_nag, disable_project_nag, set_task_parent, link_project_to_trello, unlink_project_from_trello, create_trello_task, adopt_trello_card, check_trello_item, set_project_order, set_project_dependency, set_goal_order, set_goal_dependency
from tools.link_tool import link_entities, get_entity_links, unlink_entities
from tools.notification_tool import get_recent_notifications
from tools.artifact_tool import attach_artifact, read_artifact, list_entity_artifacts, delete_artifact_by_id
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

__all__ = [
    "get_current_time", 
    "calculate", 
    "echo",
    "create_tool",
    "update_tool",
    "list_tool_files",
    "read_tool",
    "delete_tool",
    "register_tool",
    "unregister_tool",
    "restart_mcp_server",
    "start_mcp_server",
    "stop_mcp_server",
    "mcp_server_status",
    "get_current_weather_by_zip",
    "get_rain_chance_by_zip",
    "get_hourly_forecast_by_zip",
    "glob_search",
    "get_tool_creation_guide",
    "remember",
    "recall",
    "forget",
    "ping_host",
    "grep_search",
    "curl_request",
    "learn_from_url",
    "query_knowledge",
    "list_knowledge_sources",
    "remove_knowledge_source",
    "search_chat_history",
    "list_chat_users",
    "os_level_find",
    "cat_file",
    "ls_dir",
    "tail_file",
    "json_validate_file",
    "yaml_validate_file",
    "send_pushover_notification",
    "set_reminder",
    "get_reminders",
    "cancel_reminder_by_id",
    "modify_reminder_by_id",
    "set_nag",
    "snooze_reminder",
    "create_goal",
    "create_project",
    "create_task",
    "update_item",
    "get_goals_summary",
    "get_goal_detail",
    "get_project_detail",
    "get_entity_detail",
    "get_my_tasks",
    "search_goals",
    "update_entity_notes",
    "get_entity_notes",
    "set_due_reminder",
    "delete_item",
    "set_task_order",
    "set_task_dependency",
    "enable_project_nag",
    "disable_project_nag",
    "set_task_parent",
    "link_project_to_trello",
    "unlink_project_from_trello",
    "create_trello_task",
    "adopt_trello_card",
    "set_project_order",
    "set_project_dependency",
    "set_goal_order",
    "set_goal_dependency",
    "create_list",
    "show_list",
    "show_all_lists",
    "add_list_item",
    "remove_list_item",
    "move_list_items",
    "sync_list",
    "trello_show_board",
    "trello_add_card",
    "trello_move_card",
    "trello_archive_card",
    "trello_list_boards",
    "trello_suggest_list",
    "trello_get_card",
    "trello_update_card",
    "trello_card_checklist",
    "trello_add_comment",
    "trello_card_labels",
    "trello_board_labels",
    "connect_trello_board",
    "disconnect_trello_board",
    "set_list_aliases",
    "set_item_tracking",
    "link_entities",
    "get_entity_links",
    "unlink_entities",
    "get_recent_notifications",
    "attach_artifact",
    "read_artifact",
    "list_entity_artifacts",
    "delete_artifact_by_id",
    "create_job",
    "get_jobs",
    "update_job",
    "run_job",
    "internet_search",
    "git_tool",
    "get_guide",
    "create_doc",
    "get_doc",
    "update_doc",
    "append_to_doc",
    "search_docs",
    "list_docs",
    "update_doc_meta",
    "delete_doc",
    "enhance_doc",
    "start_research",
    "check_research",
    "cancel_research",
    "list_research_jobs",
    "refine_research",
    "print_doc",
    "list_focus",
    "promote_focus",
    "clear_focus",
    "get_backlog_summary",
    "get_family_focus",
    "create_idea",
    "list_ideas",
    "search_ideas",
    "get_idea",
    "update_idea",
    "delete_idea",
    "graduate_idea",
    "update_idea_document",
    "append_to_idea_document",
    "read_idea_document",
    "revise_idea_document",
    "respond_to_scrum_item",
    "get_pending_scrum_items",
    "check_skipper_inbox",
    "read_skipper_email",
    "send_skipper_email",
    "search_skipper_email",
    "create_folder",
    "get_folder",
    "list_folders",
    "add_to_folder",
    "create_doc_in_folder",
    "remove_from_folder",
    "move_to_folder",
    "delete_folder",
    "restore_folder",
    "search_folders",
    "add_behavior",
    "list_behaviors",
    "update_behavior",
    "remove_behavior",
    "toggle_behavior",
]
