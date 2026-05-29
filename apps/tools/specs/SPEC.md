# Tools — App Spec

## Purpose
Read-only browser for the chat-agent's tool-routing registry —
categories, the tools each category exposes, the long-form prompt
guide markdown beside each tool, and the keyword routes that bring
each category into the chat context window.

## What this app owns
- The Tools UI (`apps/tools/ui/ToolsApp.jsx`) and its launcher tile.
- `GET /api/apps/tools/categories` — flatten the merged registry
  (legacy `tool_routes.json` + packaged apps' tool categories)
  into one list.
- `GET /api/apps/tools/guide/{guide_name}` — serve a guide markdown
  file from `prompts/guides/`. Path traversal is rejected.

## What this app does NOT own
- The tool registrations themselves — those come from each app's
  `manifest.yaml` tool_category + `tools.py` (preferred) or from
  the legacy `tool_routes.json` (anything not yet packaged).
- The guide markdown files — those live in each app's
  `apps/<id>/guide.md` (packaged) or `prompts/guides/<id>.md`
  (legacy). The route resolves both.

## Migrations
None. Tools is read-only.
