import os
from dotenv import load_dotenv
load_dotenv()

import os
import json
from typing import Any, List, Tuple


def json_validate_file(path: str, max_errors: int = 5) -> str:
    """Validate that a JSON file is well-formed and report details.

    Args:
        path: File path relative to the app root (e.g. "data/config.json").
        max_errors: Maximum number of error details to return (default 5).

    Returns:
        A formatted string indicating whether the JSON is valid. If invalid, includes
        line/column (when available) and a short context snippet.
    """
    try:
        if not path or not isinstance(path, str):
            return "Error in json_validate_file: 'path' must be a non-empty string."

        # Basic path safety checks
        if os.path.isabs(path):
            return "Error in json_validate_file: absolute paths are not allowed."
        if ".." in path.split(os.sep):
            return "Error in json_validate_file: path traversal ('..') is not allowed."

        app_root = os.path.abspath(os.getcwd())
        target_path = os.path.abspath(os.path.join(app_root, path))
        if not (target_path == app_root or target_path.startswith(app_root + os.sep)):
            return "Error in json_validate_file: path escapes the app root."

        if not os.path.exists(target_path):
            return f"Error in json_validate_file: file not found: {path}"
        if os.path.isdir(target_path):
            return f"Error in json_validate_file: path is a directory, not a file: {path}"

        # Read as text (utf-8). If the file is not utf-8, surface a clean error.
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            return (
                "Invalid JSON (or non-UTF8 file): unable to decode as UTF-8. "
                "If this is JSON, ensure it is saved as UTF-8."
            )

        # Empty file is invalid JSON
        if text.strip() == "":
            return f"Invalid JSON: file is empty: {path}"

        try:
            obj: Any = json.loads(text)
        except json.JSONDecodeError as e:
            # Provide a small context window around the error
            line = e.lineno
            col = e.colno
            msg = e.msg

            lines = text.splitlines()
            context: List[str] = []
            start = max(1, line - 2)
            end = min(len(lines), line + 2)
            width = len(str(end))

            for i in range(start, end + 1):
                prefix = ">" if i == line else " "
                context.append(f"{prefix} {str(i).rjust(width)} | {lines[i-1]}")
                if i == line:
                    caret_pad = " " * (col + width + 4)  # accounts for ' X | '
                    context.append(f"  {' ' * width} |" + " " * (col - 1) + "^")

            return (
                f"Invalid JSON: {path}\n"
                f"Reason: {msg}\n"
                f"Location: line {line}, column {col}\n\n"
                + "Context:\n"
                + "\n".join(context)
            )

        # If valid, return a small summary
        summary = ""
        if isinstance(obj, dict):
            summary = f"top-level type: object (keys: {len(obj)})"
        elif isinstance(obj, list):
            summary = f"top-level type: array (length: {len(obj)})"
        else:
            summary = f"top-level type: {type(obj).__name__}"

        size_bytes = len(text.encode("utf-8"))
        return f"Valid JSON: {path}\nSummary: {summary}\nSize: {size_bytes} bytes"

    except Exception as e:
        return f"Error in json_validate_file: {str(e)}"
