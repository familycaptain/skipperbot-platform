"""
Tool Registry - Updates __init__.py and mcp_server.py to register new tools.
Uses line-by-line insertion at known anchor points for reliability.
"""

import ast
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
MCP_SERVER_PATH = os.path.join(BASE_DIR, "mcp_server.py")
INIT_PATH = os.path.join(TOOLS_DIR, "__init__.py")
TOOL_ROUTES_PATH = os.path.join(BASE_DIR, "tool_routes.json")


def register_tool(tool_name: str, function_name: str, category: str = "", keywords: str = "") -> str:
    """
    Register a tool by updating __init__.py, mcp_server.py, and the tool router.
    
    Args:
        tool_name: Name of the tool file (without .py extension, e.g., 'weather_tool')
        function_name: Name of the function to import and register
        category: Tool router category to add this tool to (e.g. 'web', 'filesystem', 'utility'). If the category does not exist, it will be created.
        keywords: Comma-separated keywords that should trigger this tool's category (e.g. 'stock,stocks,portfolio,market')
    
    Returns:
        Success message or error description
    """
    if not tool_name.endswith('_tool'):
        tool_name = f"{tool_name}_tool"
    
    tool_file = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    if not os.path.exists(tool_file):
        return f"Error: Tool file '{tool_name}.py' does not exist."
    
    try:
        init_result = _update_init(tool_name, function_name)
        mcp_result = _update_mcp_server(tool_name, function_name)

        # Register in tool router
        route_result = ""
        if category:
            from tool_router import register_tool_route, create_category, TOOL_CATEGORIES
            cat = category.lower().strip()
            kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []

            # Auto-create category if it doesn't exist
            if cat not in TOOL_CATEGORIES:
                create_category(cat, f"Tools for {cat}", kw_list)
                route_result = f"Created new category '{cat}'. "

            result = register_tool_route(function_name, cat, kw_list if kw_list else None)
            route_result += result
        else:
            route_result = "Warning: No category specified — tool won't be routed to users. Use register_tool_route to add it to a category."

        # Auto-extract and register ack template from docstring
        ack_result = ""
        if category:
            ack_template = _extract_ack(tool_name, function_name)
            if ack_template:
                ack_result = _update_tool_routes_ack(cat, function_name, ack_template)
            else:
                ack_result = "No Ack: section found in docstring — skipped ack registration."

        return f"{init_result}\n{mcp_result}\n{route_result}\n{ack_result}\nTool '{function_name}' registered. Restart MCP server to apply changes."
    except Exception as e:
        return f"Error registering tool: {str(e)}"


def _extract_ack(tool_name: str, function_name: str) -> str:
    """Extract the Ack: template from a tool function's docstring."""
    tool_file = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    try:
        with open(tool_file, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                docstring = ast.get_docstring(node)
                if not docstring:
                    return ""
                # Look for "Ack:" section in docstring
                in_ack = False
                ack_lines = []
                for line in docstring.split('\n'):
                    stripped = line.strip()
                    if stripped.lower().startswith('ack:'):
                        in_ack = True
                        # Check if ack is on the same line as the header
                        after = stripped[4:].strip()
                        if after:
                            ack_lines.append(after)
                        continue
                    if in_ack:
                        # Stop at the next section header or end
                        if stripped and not stripped[0].isspace() and stripped.endswith(':') and len(stripped) > 1:
                            break
                        if stripped:
                            ack_lines.append(stripped)
                        elif ack_lines:
                            break  # blank line after content = end of section
                return ' '.join(ack_lines).strip() if ack_lines else ""
    except Exception:
        return ""
    return ""


def _update_tool_routes_ack(category: str, function_name: str, ack_template: str) -> str:
    """Add an ack template for a tool. Persisted via tool_router into the
    gitignored local overlay (tool_routes.local.json) — NOT the tracked
    tool_routes.json — so runtime writes can never conflict with a deploy."""
    try:
        from tool_router import set_local_ack
        return set_local_ack(category, function_name, ack_template)
    except Exception as e:
        return f"Warning: Failed to add ack — {str(e)}"


def _update_init(tool_name: str, function_name: str) -> str:
    """Update __init__.py to include the new tool import and export."""
    with open(INIT_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    import_line = f"from tools.{tool_name} import {function_name}"
    all_entry = f'    "{function_name}",'
    
    if import_line in content and function_name in content:
        return f"Already registered in __init__.py"
    
    lines = content.split('\n')
    new_lines = []
    import_inserted = False
    all_inserted = False

    # Find the true end of the last import (accounting for multi-line blocks)
    last_import_end = -1
    i = 0
    while i < len(lines):
        if lines[i].startswith('from tools.'):
            if '(' in lines[i] and ')' not in lines[i]:
                # Multi-line import — find closing ')'
                while i < len(lines) and ')' not in lines[i]:
                    i += 1
            last_import_end = i
        i += 1

    for i, line in enumerate(lines):
        new_lines.append(line)

        if not import_inserted and i == last_import_end and import_line not in content:
            new_lines.append(import_line)
            import_inserted = True
        
        if not all_inserted and line.strip() == ']':
            if import_line not in content or function_name not in content:
                new_lines.insert(-1, all_entry)
                all_inserted = True
    
    with open(INIT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    
    return f"Updated __init__.py with {function_name}"


def _update_mcp_server(tool_name: str, function_name: str) -> str:
    """Update mcp_server.py to import and register the new tool."""
    with open(MCP_SERVER_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    import_line = f"from tools.{tool_name} import {function_name}"
    register_line = f"mcp.tool()({function_name})"
    
    if import_line in content and register_line in content:
        return f"Already registered in mcp_server.py"
    
    lines = content.split('\n')
    new_lines = []
    
    # Find the true end of the last import (accounting for multi-line blocks)
    last_import_end = -1
    last_register_idx = -1
    i = 0
    while i < len(lines):
        if lines[i].startswith('from tools.'):
            if '(' in lines[i] and ')' not in lines[i]:
                # Multi-line import — find closing ')'
                while i < len(lines) and ')' not in lines[i]:
                    i += 1
            last_import_end = i
        if lines[i].startswith('mcp.tool()'):
            last_register_idx = i
        i += 1
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        if i == last_import_end and import_line not in content:
            new_lines.append(import_line)
        if i == last_register_idx and register_line not in content:
            new_lines.append(register_line)
    
    with open(MCP_SERVER_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    
    return f"Updated mcp_server.py with {function_name}"


def unregister_tool(tool_name: str, function_name: str) -> str:
    """
    Unregister a tool by removing it from __init__.py and mcp_server.py.
    Does not delete the tool file itself.
    
    Args:
        tool_name: Name of the tool file (without .py extension)
        function_name: Name of the function to remove
    
    Returns:
        Success message or error description
    """
    if not tool_name.endswith('_tool'):
        tool_name = f"{tool_name}_tool"
    
    try:
        import_line = f"from tools.{tool_name} import {function_name}"
        
        with open(INIT_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(INIT_PATH, 'w', encoding='utf-8') as f:
            for line in lines:
                if import_line in line:
                    continue
                if f'"{function_name}"' in line and '__all__' not in line:
                    continue
                f.write(line)
        
        with open(MCP_SERVER_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(MCP_SERVER_PATH, 'w', encoding='utf-8') as f:
            for line in lines:
                if import_line in line:
                    continue
                if f"mcp.tool()({function_name})" in line:
                    continue
                f.write(line)

        # Remove from tool router
        from tool_router import unregister_tool_route
        unregister_tool_route(function_name)
        
        return f"Unregistered tool '{function_name}'. Restart MCP server to apply changes."
    except Exception as e:
        return f"Error unregistering tool: {str(e)}"
