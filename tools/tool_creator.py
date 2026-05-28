"""
Tool Creator - Creates new tool Python files dynamically
"""

import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))

# Late import to avoid circular deps
def _log_tool_change(action: str, tool_name: str, summary: str = ""):
    try:
        sys.path.insert(0, os.path.dirname(TOOLS_DIR))
        from auto_memory import log_entity_change
        log_entity_change(action, tool_name, "tool", summary or tool_name)
    except Exception:
        pass

DOTENV_HEADER = """import os
from dotenv import load_dotenv
load_dotenv()
"""


def create_tool(tool_name: str, tool_code: str) -> str:
    """
    Create a new tool Python file in the tools folder.
    
    Args:
        tool_name: Name of the tool (will be used as filename, e.g., 'weather_tool')
        tool_code: The complete Python code for the tool file, including the function definition
    
    Returns:
        Success message or error description
    """
    if not re.match(r'^[a-z][a-z0-9_]*$', tool_name):
        return f"Error: Invalid tool name '{tool_name}'. Use lowercase letters, numbers, and underscores only."
    
    if not tool_name.endswith('_tool'):
        tool_name = f"{tool_name}_tool"
    
    file_path = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    
    if os.path.exists(file_path):
        return f"Error: Tool file '{tool_name}.py' already exists. Use update_tool to modify it."
    
    try:
        final_code = _ensure_dotenv(tool_code)
        syntax_err = _validate_syntax(final_code, f"{tool_name}.py")
        if syntax_err:
            return syntax_err
        dep_error, dep_warning = _check_dependencies(final_code)
        if dep_error:
            return dep_error
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(final_code)
        msg = f"Successfully created tool file: {tool_name}.py"
        if dep_warning:
            msg += f"\n\n{dep_warning}"
        _log_tool_change("created", tool_name, f"New tool file: {tool_name}.py")
        return msg
    except Exception as e:
        return f"Error creating tool file: {str(e)}"


def update_tool(tool_name: str, tool_code: str) -> str:
    """
    Update an existing tool Python file in the tools folder.
    
    Args:
        tool_name: Name of the tool (e.g., 'weather_tool')
        tool_code: The complete Python code for the tool file
    
    Returns:
        Success message or error description
    """
    if not tool_name.endswith('_tool'):
        tool_name = f"{tool_name}_tool"
    
    file_path = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    
    if not os.path.exists(file_path):
        return f"Error: Tool file '{tool_name}.py' does not exist. Use create_tool to create it."
    
    try:
        # Backup existing file in case validation fails
        with open(file_path, 'r', encoding='utf-8') as f:
            backup = f.read()
        final_code = _ensure_dotenv(tool_code)
        syntax_err = _validate_syntax(final_code, f"{tool_name}.py")
        if syntax_err:
            return syntax_err
        dep_error, dep_warning = _check_dependencies(final_code)
        if dep_error:
            return dep_error
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(final_code)
        msg = f"Successfully updated tool file: {tool_name}.py"
        if dep_warning:
            msg += f"\n\n{dep_warning}"
        _log_tool_change("updated", tool_name, f"Tool file updated: {tool_name}.py")
        return msg
    except Exception as e:
        # Restore backup on failure
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(backup)
        except Exception:
            pass
        return f"Error updating tool file: {str(e)}"


# Well-known PyPI package name → import name mappings
_PYPI_TO_IMPORT = {
    "beautifulsoup4": "bs4",
    "python-dotenv": "dotenv",
    "discord.py": "discord",
    "pillow": "PIL",
    "scikit-learn": "sklearn",
    "pyyaml": "yaml",
    "opencv-python": "cv2",
    "python-dateutil": "dateutil",
}


def _get_requirements_imports() -> set[str]:
    """Parse requirements.txt and return the set of importable module names."""
    req_path = os.path.join(os.path.dirname(TOOLS_DIR), "requirements.txt")
    if not os.path.exists(req_path):
        return set()
    names = set()
    try:
        with open(req_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Strip version specifiers: "fastapi>=0.109.0" → "fastapi"
                pkg = re.split(r"[>=<~!\[]", line)[0].strip()
                if not pkg:
                    continue
                # Map to import name
                if pkg.lower() in _PYPI_TO_IMPORT:
                    names.add(_PYPI_TO_IMPORT[pkg.lower()])
                else:
                    # Default: lowercase, replace hyphens with underscores
                    names.add(pkg.lower().replace("-", "_"))
    except OSError:
        pass
    return names


def _extract_imports(code: str) -> set[str]:
    """Extract top-level imported module names from Python source code."""
    modules = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return modules
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
    return modules


def _check_dependencies(code: str) -> tuple[str, str]:
    """Check if imported packages are installed and in requirements.txt.

    Returns:
        (error, warning) — error is non-empty if packages are not installed
        (blocks save). warning is non-empty if packages are installed but
        not in requirements.txt (allows save, but warns).
    """
    imports = _extract_imports(code)
    if not imports:
        return "", ""

    # Get stdlib module names
    stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    # Also treat these as safe (always available in our environment)
    stdlib |= {"dotenv", "tools"}

    # Get packages from requirements.txt
    req_imports = _get_requirements_imports()

    not_installed = []
    not_in_requirements = []

    for mod in sorted(imports):
        if mod in stdlib:
            continue
        # Check if actually importable on this system
        installed = importlib.util.find_spec(mod) is not None
        in_req = mod in req_imports

        if not installed:
            not_installed.append(mod)
        elif not in_req:
            not_in_requirements.append(mod)

    error = ""
    warning = ""

    if not_installed:
        error = (
            f"Error: Tool code was NOT saved. The following packages are not installed "
            f"and will crash the MCP server on restart: {', '.join(not_installed)}\n"
            f"Install them first, then try again:\n"
            f"  pip install {' '.join(not_installed)}\n"
            f"Then add them to requirements.txt."
        )

    if not_in_requirements:
        warning = (
            f"⚠️  These packages are installed but NOT in requirements.txt: "
            f"{', '.join(not_in_requirements)}\n"
            f"Add them to requirements.txt for reproducibility."
        )

    return error, warning


def _validate_syntax(code: str, filename: str) -> str | None:
    """Write code to a temp file and run python3 to check for syntax errors.
    Returns an error string if invalid, or None if OK."""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        result = subprocess.run(
            [sys.executable, '-c', f'import py_compile; py_compile.compile(r"{tmp_path}", doraise=True)'],
            capture_output=True, text=True, timeout=10
        )
        os.unlink(tmp_path)
        if result.returncode != 0:
            err = result.stderr.strip().split('\n')[-1] if result.stderr.strip() else 'Unknown syntax error'
            return f"Syntax error in {filename} — code was NOT saved:\n{err}"
        return None
    except subprocess.TimeoutExpired:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return f"Syntax check timed out for {filename} — code was NOT saved."
    except Exception as e:
        return f"Syntax validation failed for {filename}: {str(e)}"


def _ensure_dotenv(code: str) -> str:
    """Ensure tool code includes dotenv loading. Injects it if missing.
    Handles __future__ imports by inserting dotenv after them."""
    if "load_dotenv" in code:
        return code
    lines = code.split("\n")
    insert_at = 0
    # Skip past module docstring if present
    if lines and lines[0].strip().startswith('"""'):
        for i, line in enumerate(lines):
            if i > 0 and '"""' in line:
                insert_at = i + 1
                break
        else:
            insert_at = len(lines)
    elif lines and lines[0].strip().startswith("'''"):
        for i, line in enumerate(lines):
            if i > 0 and "'''" in line:
                insert_at = i + 1
                break
        else:
            insert_at = len(lines)
    # Always inject full header (import os must precede load_dotenv)
    lines.insert(insert_at, DOTENV_HEADER)
    # Re-split so every element is a single line, then deduplicate 'import os'
    all_lines = "\n".join(lines).split("\n")
    seen_os = False
    deduped = []
    for ln in all_lines:
        if ln.strip() == "import os":
            if not seen_os:
                seen_os = True
                deduped.append(ln)
            # else skip duplicate
        else:
            deduped.append(ln)
    return "\n".join(deduped)


def list_tool_files() -> str:
    """
    List all tool files in the tools folder.
    
    Returns:
        List of tool filenames
    """
    try:
        files = [f for f in os.listdir(TOOLS_DIR) 
                 if f.endswith('_tool.py') and not f.startswith('__')]
        return f"Tool files: {', '.join(sorted(files))}"
    except Exception as e:
        return f"Error listing tools: {str(e)}"


def read_tool(tool_name: str) -> str:
    """
    Read the contents of a tool file.
    
    Args:
        tool_name: Name of the tool (e.g., 'weather_tool')
    
    Returns:
        The contents of the tool file
    """
    if not tool_name.endswith('_tool'):
        tool_name = f"{tool_name}_tool"
    
    file_path = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    
    if not os.path.exists(file_path):
        return f"Error: Tool file '{tool_name}.py' does not exist."
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading tool file: {str(e)}"


def delete_tool(tool_name: str) -> str:
    """
    Delete a tool Python file from the tools folder.
    Note: You should call unregister_tool first to remove it from mcp_server.py and __init__.py.
    
    Args:
        tool_name: Name of the tool (e.g., 'weather_tool')
    
    Returns:
        Success message or error description
    """
    if not tool_name.endswith('_tool'):
        tool_name = f"{tool_name}_tool"
    
    protected_tools = ['time_tool', 'calculator_tool', 'echo_tool', 'tool_creator', 'tool_registry', 'mcp_control']
    if tool_name.replace('_tool', '') in [t.replace('_tool', '') for t in protected_tools]:
        return f"Error: Cannot delete protected system tool '{tool_name}'."
    
    file_path = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    
    if not os.path.exists(file_path):
        return f"Error: Tool file '{tool_name}.py' does not exist."
    
    try:
        os.remove(file_path)
        _log_tool_change("deleted", tool_name, f"Tool file deleted: {tool_name}.py")
        return f"Successfully deleted tool file: {tool_name}.py"
    except Exception as e:
        return f"Error deleting tool file: {str(e)}"
