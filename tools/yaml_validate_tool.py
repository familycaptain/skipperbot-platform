import os
from dotenv import load_dotenv
load_dotenv()

import os
from typing import Any


def yaml_validate_file(path: str, max_errors: int = 5) -> str:
    """Validate a YAML file within the app folder.

    Parses a YAML file and reports whether it is valid. If invalid, returns the
    error with line/column when available.

    Args:
        path: Relative path (from app root) to the YAML file.
        max_errors: Maximum number of error details to include (best-effort; YAML parsers typically raise one error).

    Returns:
        A formatted string indicating whether the YAML is valid, plus a brief summary
        (top-level type, number of keys/items) or error details.
    """
    try:
        if not path or not isinstance(path, str):
            return "Error in yaml_validate_file: 'path' must be a non-empty string."

        # Resolve app root (directory containing agent.py)
        app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        # Disallow obvious traversal and absolute paths early
        if os.path.isabs(path):
            return "Error in yaml_validate_file: absolute paths are not allowed. Provide a path relative to the app root."

        candidate = os.path.abspath(os.path.join(app_root, path))
        if not (candidate == app_root or candidate.startswith(app_root + os.sep)):
            return "Error in yaml_validate_file: path escapes the app root."

        if not os.path.exists(candidate):
            return f"Error in yaml_validate_file: file not found: {path}"
        if os.path.isdir(candidate):
            return f"Error in yaml_validate_file: path is a directory, expected a file: {path}"

        # Lazy import so the tool loads even if dependency is missing
        try:
            import yaml  # type: ignore
        except Exception:
            return (
                "Error in yaml_validate_file: PyYAML is not installed. "
                "Add 'pyyaml' to requirements.txt and redeploy/restart."
            )

        with open(candidate, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        try:
            data: Any = yaml.safe_load(content)
        except Exception as e:
            # Best-effort extraction of line/column if present (PyYAML MarkedYAMLError)
            line_info = ""
            try:
                mark = getattr(e, "problem_mark", None)
                if mark is not None:
                    # PyYAML uses 0-based line/column internally
                    line_info = f" (line {mark.line + 1}, column {mark.column + 1})"
            except Exception:
                pass

            msg = str(e).strip()
            # Cap output a bit
            if len(msg) > 1500:
                msg = msg[:1500] + "…"

            return f"Invalid YAML{line_info}: {msg}"

        # Summary
        if data is None:
            summary = "top-level: null (empty document)"
        elif isinstance(data, dict):
            keys = list(data.keys())
            preview = ", ".join([str(k) for k in keys[:10]])
            more = "" if len(keys) <= 10 else f" (+{len(keys) - 10} more)"
            summary = f"top-level: mapping (keys={len(keys)}; first keys: {preview}{more})"
        elif isinstance(data, list):
            summary = f"top-level: sequence (items={len(data)})"
        else:
            summary = f"top-level: {type(data).__name__}"

        size = len(content.encode("utf-8", errors="replace"))
        return f"Valid YAML: {path}\nSummary: {summary}\nSize: {size} bytes"

    except Exception as e:
        return f"Error in yaml_validate_file: {str(e)}"