import os
from dotenv import load_dotenv
load_dotenv()

import os
import glob
from typing import List


def glob_search(pattern: str, include_files: bool = True, include_dirs: bool = True, max_results: int = 200) -> str:
    """Search for files and/or directories under the app root using a glob pattern.

    This tool is intentionally sandboxed to only search within the application's root
    directory (the current working directory of the MCP server process). It performs
    a recursive glob search (supports **).

    Args:
        pattern: Glob pattern relative to the app root. Examples:
            - "*.py"
            - "tools/*.py"
            - "**/*.md"
            - "**/mcp_server.py"
        include_files: Whether to include files in results.
        include_dirs: Whether to include directories in results.
        max_results: Maximum number of results to return.

    Returns:
        A formatted string with matched paths (relative to app root), one per line.
    """
    try:
        root = os.path.abspath(os.getcwd())

        # Normalize and prevent absolute paths / escaping the root.
        if os.path.isabs(pattern):
            return "Error: pattern must be a relative glob (not an absolute path)."

        # Disallow obvious traversal attempts; still also enforce root containment later.
        if pattern.startswith("../") or pattern.startswith("..\\") or ".." + os.sep in pattern:
            return "Error: pattern must not traverse outside the app root (no '..')."

        search_pattern = os.path.join(root, pattern)

        matches: List[str] = glob.glob(search_pattern, recursive=True)

        skip_dirs = {".git", "node_modules", "__pycache__", ".gradle", ".kotlin", ".venv", "build"}
        filtered: List[str] = []
        for p in matches:
            ap = os.path.abspath(p)
            # Enforce containment in root
            if not (ap == root or ap.startswith(root + os.sep)):
                continue
            rel = os.path.relpath(ap, root)
            # Skip noisy directories
            parts = rel.replace("\\", "/").split("/")
            if any(part in skip_dirs for part in parts):
                continue
            if os.path.isfile(ap) and not include_files:
                continue
            if os.path.isdir(ap) and not include_dirs:
                continue
            filtered.append(rel)

        # Sort for stable output
        filtered.sort()

        total = len(filtered)
        if total == 0:
            return f"No matches for pattern: {pattern}"

        if total > max_results:
            shown = filtered[:max_results]
            return (
                f"Matches for pattern: {pattern}\n"
                f"Showing {max_results} of {total} results:\n" + "\n".join(shown)
            )

        return f"Matches for pattern: {pattern}\n" + "\n".join(filtered)
    except Exception as e:
        return f"Error in glob_search: {str(e)}"
