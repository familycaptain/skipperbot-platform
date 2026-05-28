import os
from dotenv import load_dotenv
load_dotenv()

import os
import shlex
import subprocess
from typing import List, Optional


def grep_search(
    pattern: str,
    path: str = ".",
    args: str = "-n",
    max_output_chars: int = 20000,
) -> str:
    """Search text in files under the application root using grep.

    This tool is sandboxed to only operate within the application root directory.
    You can pass custom grep arguments (e.g., recursive, case-insensitive, include/exclude).

    Args:
        pattern: The grep pattern to search for (passed as the PATTERN argument to grep).
        path: File or directory (relative to app root) to search within.
        args: Additional grep arguments as a single string (e.g., "-RIn --exclude-dir=.git").
              Note: The tool will reject dangerous flags and any attempt to search outside the app root.
        max_output_chars: Maximum number of characters to return from grep output.

    Returns:
        A formatted string containing grep results or an informative error message.
    """

    app_root = os.getcwd()

    # Basic path hardening
    if os.path.isabs(path):
        return "Error: 'path' must be relative to the application root (absolute paths are not allowed)."
    if "\x00" in path:
        return "Error: Invalid path."

    target_abs = os.path.abspath(os.path.join(app_root, path))
    if not (target_abs == app_root or target_abs.startswith(app_root + os.sep)):
        return "Error: 'path' escapes the application root; operation not permitted."

    # Parse args safely
    try:
        arg_list: List[str] = shlex.split(args) if args else []
    except ValueError as e:
        return f"Error: Could not parse args: {e}"

    # Block risky/irrelevant flags
    blocked_prefixes = {
        "--binary-files",  # can cause huge outputs; behavior varies
        "--devices",
        "--directories",
        "--exclude-from",  # reads external file list
        "--files-with-matches",  # could be fine, but keep output predictable
        "--files-without-match",
        "--include-from",  # reads external file list
        "--null",
        "--null-data",
    }
    blocked_exact = {
        "-D",  # --devices
        "-d",  # --directories
        "-Z",  # --null
    }

    for a in arg_list:
        if a in blocked_exact:
            return f"Error: Disallowed grep argument: {a}"
        for pref in blocked_prefixes:
            if a == pref or a.startswith(pref + "="):
                return f"Error: Disallowed grep argument: {a}"

    # Force a safe-ish baseline: no colors, stable output, treat as text
    # Auto-exclude noisy dirs when doing recursive searches
    is_recursive = any(a in ("-r", "-R", "--recursive", "-rn", "-Rn", "-RIn", "-rIn") or
                        a.startswith("-") and "r" in a.lstrip("-")[:3]
                        for a in arg_list)
    base_args = ["--color=never"]
    if is_recursive:
        base_args += ["--include=*.py", "--include=*.md",
                      "--include=*.js", "--include=*.jsx",
                      "--include=*.json", "--include=*.yaml",
                      "--include=*.yml", "--include=*.sql",
                      "--include=*.txt", "--include=*.html",
                      "--include=*.css", "--include=*.toml",
                      "--exclude-dir=.git", "--exclude-dir=node_modules",
                      "--exclude-dir=__pycache__"]

    # Find grep binary — on Windows, fall back to Git for Windows' bundled grep
    grep_bin = "grep"
    if os.name == "nt":
        git_grep = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                "Git", "usr", "bin", "grep.exe")
        if os.path.isfile(git_grep):
            grep_bin = git_grep

    cmd = [grep_bin] + base_args + arg_list + [pattern, target_abs]

    try:
        proc = subprocess.run(
            cmd,
            cwd=app_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except FileNotFoundError:
        return "Error: 'grep' is not available in this environment."
    except subprocess.TimeoutExpired:
        return "Error: grep timed out (90s). Try narrowing the search or reducing recursion."
    except Exception as e:
        return f"Error: Failed to run grep: {e}"

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # grep exit codes: 0 match, 1 no match, 2 error
    if proc.returncode == 1:
        return "No matches found."
    if proc.returncode == 2:
        # Provide stderr but keep it bounded
        msg = stderr.strip() or "grep returned an error."
        if len(msg) > 2000:
            msg = msg[:2000] + "\n... (truncated)"
        return f"Error: {msg}"

    out = stdout
    if stderr.strip():
        out = out + ("\n\n[stderr]\n" + stderr)

    if len(out) > max_output_chars:
        out = out[:max_output_chars] + "\n... (truncated)"

    return out.strip()