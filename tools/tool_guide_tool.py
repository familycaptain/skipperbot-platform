"""
Tool Guide - Returns detailed specifications for creating and modifying tools.
"""

import os
from dotenv import load_dotenv
load_dotenv()


def get_tool_creation_guide() -> str:
    """Get the full specification and rules for creating or modifying MCP tools.

    Call this tool BEFORE creating or updating any tool to get the latest
    coding standards, security rules, and step-by-step instructions.

    Returns:
        Detailed guide for tool creation and modification.
    """
    try:
        return """
=== TOOL CREATION & MODIFICATION GUIDE ===

STEPS TO CREATE A NEW TOOL:
1. Use create_tool to write a new Python tool file
2. Use register_tool to add it to the MCP server AND the tool router
   - You MUST provide a category and keywords, or the tool won't be routed to users!
   - Example: register_tool("stock_tool", "get_stock_price", category="finance", keywords="stock,stocks,portfolio,market,price,shares")
   - Use an existing category if one fits, or a new category name to auto-create it
   - Available categories: core, filesystem, web, knowledge, system, utility, messaging (or create new ones)
3. Use restart_mcp_server to reload with the new tool
4. The new tool will then be available for use

ACK TEMPLATES (auto-handled by register_tool):
- register_tool automatically reads the Ack: section from the tool's docstring
  and adds it to tool_routes.json — you do NOT need to edit tool_routes.json manually
- If no Ack: section is found, the tool will have no ack message
- EVERY tool should have an Ack: section in its docstring

STEPS TO MODIFY AN EXISTING TOOL:
1. Use read_tool to view the current code
2. Use update_tool to write the updated code
3. Use restart_mcp_server to reload

IMPORT PLACEMENT (CRITICAL):
- register_tool adds imports to mcp_server.py and tools/__init__.py automatically
- If you ever need to manually add an import, place it as a STANDALONE single-line import
- NEVER insert an import inside a multi-line 'from X import (' block — this causes SyntaxError
- Place new imports BEFORE any multi-line import blocks, not inside them

CODING STANDARDS:
- Tool files go in the tools/ folder, one function per file
- Filename must end with _tool.py (e.g. weather_tool.py)
- Use type hints for all parameters and return values
- Return a formatted string, not dicts or raw objects
- Use urllib.request for HTTP calls (available in stdlib) or requests if needed
- dotenv is auto-injected into all tool files; you do not need to add it
- The ENTIRE function body must be wrapped in a try/except that returns a readable error string
- Never let exceptions propagate unhandled — always catch and return an error message
- create_tool and update_tool will run a syntax check before saving; malformed code will be rejected

DOCSTRING FORMAT (CRITICAL - FastMCP parses these to register tools):
- The function docstring becomes the tool description that OpenAI sees
- First line: concise summary of what the tool does (this is the tool description)
- Args section: each param on its own line as "param_name: description"
- Returns section: describe what the tool returns
- FastMCP uses the Args descriptions for per-parameter descriptions in the schema
- A poor or missing docstring means OpenAI won't know when/how to use the tool
- Format must be Google-style docstrings (see example below)
- Include an Ack: section with the user-facing progress message template
  - Use {param_name} placeholders for tool arguments
  - Example: Ack: Checking stock price for {symbol}...
  - This is extracted automatically by register_tool and added to tool_routes.json

ENVIRONMENT VARIABLES & API KEYS:
- API keys and secrets MUST be stored in the .env file, NEVER hardcoded
- Access keys with os.getenv("KEY_NAME") in your tool functions
- When a tool requires a new API key, inform the user to add it to .env
- Naming convention: SERVICE_API_KEY (e.g. WEATHER_API_KEY, GITHUB_TOKEN)

SCOPE RESTRICTIONS (CRITICAL):
- NEVER create helper tools or meta-tools to edit config files (tool_routes.json, etc.)
- NEVER create tools whose sole purpose is to support other tool creation steps
- register_tool handles ALL registration automatically — imports, routing, and ack templates
- If you need something that register_tool doesn't do, tell the user

FILESYSTEM RESTRICTIONS (CRITICAL):
- Tools MUST NOT access, read, write, or reference any path outside the application root
- All file operations must be relative to the app root (the directory containing agent.py)
- NEVER use absolute paths to locations outside the app root
- If a tool resolves paths, always verify they stay within the app root before accessing
- Reject any user-provided path that escapes the app root (e.g. paths containing '..')
- Use os.path.abspath() and check startswith(app_root) to enforce containment

EXAMPLE TOOL TEMPLATE:
    \"\"\"
    Description of what this tool does.
    \"\"\"

    import os
    import urllib.request
    import json

    def my_tool_name(param1: str, param2: int = 10) -> str:
        \"\"\"One-line description.

        Args:
            param1: Description of param1.
            param2: Description of param2.

        Returns:
            Formatted string with results.

        Ack: Doing something with {param1}...
        \"\"\"
        try:
            # Tool logic here
            return f"Result: {param1}, {param2}"
        except Exception as e:
            return f"Error in my_tool_name: {str(e)}"
""".strip()
    except Exception as e:
        return f"Error in get_tool_creation_guide: {str(e)}"
