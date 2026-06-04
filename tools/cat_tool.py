import os
from dotenv import load_dotenv
load_dotenv()

from tools.secret_guard import deny_if_secret


def cat_file(path: str, max_chars: int = 20000) -> str:
    """Read a text file within the app folder (sandboxed cat).

    Args:
        path: File path relative to the app root (e.g. "requirements.txt" or "docs/readme.md").
        max_chars: Maximum number of characters to return from the file.

    Returns:
        The file contents (optionally truncated), or an error message.
    """
    try:
        try:
            max_chars = int(max_chars)
        except Exception:
            max_chars = 20000
        max_chars = max(1, min(200000, max_chars))

        app_root = os.path.abspath(os.getcwd())
        if not path or os.path.isabs(path):
            return "Error: path must be relative to the app root"

        normalized = os.path.normpath(path)
        abs_path = os.path.abspath(os.path.join(app_root, normalized))
        if not abs_path.startswith(app_root + os.sep) and abs_path != app_root:
            return "Error: path escapes the app root"

        secret_err = deny_if_secret(abs_path)
        if secret_err:
            return secret_err

        if not os.path.exists(abs_path):
            return f"Error: file not found: {path}"
        if os.path.isdir(abs_path):
            return f"Error: path is a directory: {path}"

        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 1)

        truncated = len(content) > max_chars
        content = content[:max_chars]

        header = f"--- {path} ---\n"
        if truncated:
            footer = f"\n\n[truncated to {max_chars} chars]"
        else:
            footer = ""
        return header + content + footer
    except Exception as e:
        return f"Error in cat_file: {str(e)}"