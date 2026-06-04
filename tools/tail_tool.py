import os
from dotenv import load_dotenv
load_dotenv()

import os
from typing import Optional

from tools.secret_guard import deny_if_secret


def tail_file(path: str, lines: int = 50, max_chars: int = 20000) -> str:
    """Show the end of a text file (like `tail`).

    This tool is sandboxed to only read files within the application root folder.

    Args:
        path: File path relative to the application root (e.g. "logs/app.log").
        lines: Number of lines from the end of the file to return.
        max_chars: Maximum number of characters to return (output will be truncated if needed).

    Returns:
        The last N lines of the file as text, or an error message.
    """
    try:
        if not isinstance(path, str) or not path.strip():
            return "Error in tail_file: 'path' must be a non-empty string."

        # Resolve app root as the directory containing agent.py
        app_root = os.path.abspath(os.path.dirname(__file__))
        app_root = os.path.abspath(os.path.join(app_root, ".."))

        # Reject obvious traversal attempts early
        norm = path.replace("\\", "/")
        if norm.startswith("/") or norm.startswith("~"):
            return "Error in tail_file: absolute paths are not allowed. Provide a path relative to the app root."
        if ".." in norm.split("/"):
            return "Error in tail_file: path traversal ('..') is not allowed."

        target_path = os.path.abspath(os.path.join(app_root, path))
        if not target_path.startswith(app_root + os.sep) and target_path != app_root:
            return "Error in tail_file: requested path is outside the app root."

        secret_err = deny_if_secret(target_path)
        if secret_err:
            return secret_err

        if not os.path.exists(target_path):
            return f"Error in tail_file: file not found: {path}"
        if os.path.isdir(target_path):
            return f"Error in tail_file: path is a directory, not a file: {path}"

        try:
            lines = int(lines)
        except Exception:
            return "Error in tail_file: 'lines' must be an integer."
        if lines < 1:
            return "Error in tail_file: 'lines' must be >= 1."
        if lines > 5000:
            lines = 5000

        try:
            max_chars = int(max_chars)
        except Exception:
            return "Error in tail_file: 'max_chars' must be an integer."
        if max_chars < 1000:
            max_chars = 1000
        if max_chars > 200000:
            max_chars = 200000

        # Read efficiently from the end in binary, then decode.
        # This avoids loading very large files fully into memory.
        block_size = 4096
        data = b""
        newline_count = 0

        with open(target_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            pos = file_size

            while pos > 0 and newline_count <= lines:
                read_size = block_size if pos >= block_size else pos
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                data = chunk + data
                newline_count = data.count(b"\n")

                # Safety cap: don't accumulate excessive bytes
                if len(data) > 5 * max_chars:
                    break

        # Decode with replacement to handle non-utf8 bytes
        text = data.decode("utf-8", errors="replace")
        text_lines = text.splitlines()
        tail_lines = text_lines[-lines:]
        out = "\n".join(tail_lines)

        # Truncate output to max_chars from the end (tail-like behavior)
        if len(out) > max_chars:
            out = out[-max_chars:]

        return out
    except Exception as e:
        return f"Error in tail_file: {str(e)}"