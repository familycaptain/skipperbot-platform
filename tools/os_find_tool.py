"""OS-level find tool (sandboxed to app root)."""

import os
import shlex
import subprocess
from typing import List

from tools.secret_guard import is_secret_name


def os_level_find(
    name: str = "",
    contains: str = "",
    path: str = ".",
    include_files: bool = True,
    include_dirs: bool = True,
    max_results: int = 200,
) -> str:
    """Run an OS-level `find` to locate files/directories within the app folder.

import os
from dotenv import load_dotenv
load_dotenv()

    This tool is sandboxed to only search within the application root directory
    (the directory containing agent.py). It rejects any path that attempts to
    escape the app root.

    Args:
        name: Optional glob pattern for the filename (passed to `find -name`). Example: "*.py".
        contains: Optional case-insensitive substring filter applied to the basename after `find` returns results.
        path: Subdirectory (relative to app root) to search within. Default "." (entire app root).
        include_files: Whether to include regular files in results.
        include_dirs: Whether to include directories in results.
        max_results: Maximum number of results to return.

    Returns:
        A formatted string of matched paths (relative to app root), one per line.
    """
    try:
        # Determine app root as the directory containing agent.py
        app_root = os.getcwd()
        agent_py = os.path.join(app_root, "agent.py")
        if os.path.isfile(agent_py):
            app_root = os.path.dirname(agent_py)

        # Resolve and validate search root
        if path.strip() == "":
            path = "."

        # Basic traversal guard
        if "\x00" in path:
            return "Error in os_level_find: invalid path"

        search_root = os.path.abspath(os.path.join(app_root, path))
        app_root_abs = os.path.abspath(app_root)
        if not (search_root == app_root_abs or search_root.startswith(app_root_abs + os.sep)):
            return "Error in os_level_find: path must stay within the app folder"

        if not include_files and not include_dirs:
            return "Error in os_level_find: include_files and include_dirs cannot both be False"

        # Walk the directory tree using Python (cross-platform)
        import fnmatch
        results: List[str] = []
        skip_dirs = {".git", ".ssh", "__pycache__", "node_modules", ".venv", "venv"}

        for dirpath, dirnames, filenames in os.walk(search_root):
            # Skip hidden/noisy directories
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]

            if include_dirs:
                for d in dirnames:
                    if len(results) >= max_results:
                        break
                    full = os.path.join(dirpath, d)
                    rel = os.path.relpath(full, app_root_abs)
                    base = d
                    if name and not fnmatch.fnmatch(base, name):
                        continue
                    if contains and contains.lower() not in base.lower():
                        continue
                    results.append(rel)

            if include_files:
                for f in filenames:
                    if len(results) >= max_results:
                        break
                    full = os.path.join(dirpath, f)
                    rel = os.path.relpath(full, app_root_abs)
                    base = f
                    if is_secret_name(base):
                        continue
                    if name and not fnmatch.fnmatch(base, name):
                        continue
                    if contains and contains.lower() not in base.lower():
                        continue
                    results.append(rel)

            if len(results) >= max_results:
                break

        if not results:
            return "No matches found."

        return "\n".join(results)

    except FileNotFoundError:
        return "Error in os_level_find: `find` command not available on this system"
    except Exception as e:
        return f"Error in os_level_find: {str(e)}"
