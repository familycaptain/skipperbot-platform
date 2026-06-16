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
from tools.app_help_tool import list_installed_apps, get_app_help
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
# reminders tools moved to apps/reminders/tools.py (app package).
# The platform loader auto-discovers them; no need to re-export here.
from apps.goals.tools import create_goal, create_project, create_task, update_item, stop_onboarding, get_goals_summary, get_goal_detail, get_project_detail, get_entity_detail, get_my_tasks, search_goals, update_entity_notes, get_entity_notes, set_due_reminder, delete_item, set_task_order, set_task_dependency, enable_project_nag, disable_project_nag, set_task_parent, link_project_to_trello, unlink_project_from_trello, create_trello_task, adopt_trello_card, check_trello_item, set_project_order, set_project_dependency, set_goal_order, set_goal_dependency
from tools.link_tool import link_entities, get_entity_links, unlink_entities
# notifications tools moved to apps/notifications/tools.py (app package).
# The platform loader auto-discovers them; no need to re-export here.
from tools.artifact_tool import attach_artifact, read_artifact, list_entity_artifacts, delete_artifact_by_id
# jobs tools moved to apps/jobs/tools.py (app package).
# The platform loader auto-discovers them; no need to re-export here.
# Lists + Trello tools moved to apps/lists/tools.py (app package).
# The platform loader auto-discovers them; no need to re-export here.
from tools.internet_search_tool import internet_search
from tools.git_tool import git_tool
from tools.guide_tool import get_guide
# documents tools moved to apps/documents/tools.py (app package).
# The platform loader auto-discovers them; no need to re-export here.
from tools.research_tool import start_research, check_research, cancel_research, list_research_jobs, refine_research
from tools.print_tool import print_doc
# Prioritize tools moved to apps/prioritize/tools.py (app package)
from tools.brainstorming_tool import create_idea, list_ideas, search_ideas, get_idea, update_idea, delete_idea, graduate_idea, update_idea_document, append_to_idea_document, read_idea_document, revise_idea_document
# scrum tools moved to the optional skipperbot-app-scrum package (apps/scrum/tools.py)
from tools.skipper_email_tool import check_skipper_inbox, read_skipper_email, send_skipper_email, search_skipper_email
# Folder tools moved to apps/folders/tools.py (app package)
# Behavior tools moved to apps/behaviors/tools.py (app package)
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
    # reminders tools (set_reminder, get_reminders, cancel_reminder_by_id,
    # modify_reminder_by_id, set_nag, snooze_reminder) now live at
    # apps.reminders.tools and are registered by the platform loader.
    "create_goal",
    "create_project",
    "create_task",
    "update_item",
    "stop_onboarding",
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
    # Lists + Trello tool names are no longer re-exported from `tools.*`;
    # they live at apps.lists.tools.* and are registered with the MCP server
    # by the platform loader.
    "link_entities",
    "get_entity_links",
    "unlink_entities",
    # get_recent_notifications now lives at apps.notifications.tools
    # and is registered by the platform loader.
    "attach_artifact",
    "read_artifact",
    "list_entity_artifacts",
    "delete_artifact_by_id",
    # jobs tools (create_job, get_jobs, update_job, run_job) now live at
    # apps.jobs.tools and are registered by the platform loader.
    "internet_search",
    "git_tool",
    "get_guide",
    # documents tools (create_doc, get_doc, update_doc, append_to_doc,
    # search_docs, list_docs, update_doc_meta, delete_doc, enhance_doc)
    # now live at apps.documents.tools and are registered by the loader.
    "start_research",
    "check_research",
    "cancel_research",
    "list_research_jobs",
    "refine_research",
    "print_doc",
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
    "check_skipper_inbox",
    "read_skipper_email",
    "send_skipper_email",
    "search_skipper_email",
]
