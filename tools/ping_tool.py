import os
from dotenv import load_dotenv
load_dotenv()

import platform
import re
import subprocess


def ping_host(host: str, count: int = 4, timeout_seconds: int = 3) -> str:
    """Ping an IP address or hostname and return the results.

    Args:
        host: IP address or hostname to ping (e.g., "8.8.8.8" or "example.com").
        count: Number of echo requests to send.
        timeout_seconds: Per-request timeout in seconds.

    Returns:
        A formatted string containing the ping summary and selected output lines.
    """

    host = (host or "").strip()
    if not host:
        return "Error: host is required."

    # Conservative validation to avoid shell injection and weird edge cases.
    # Allow typical hostnames, IPv4, and bracketless IPv6.
    if not re.fullmatch(r"[A-Za-z0-9.\-:]+", host):
        return "Error: host contains invalid characters."

    if count < 1 or count > 20:
        return "Error: count must be between 1 and 20."

    if timeout_seconds < 1 or timeout_seconds > 30:
        return "Error: timeout_seconds must be between 1 and 30."

    system = platform.system().lower()

    # Build platform-appropriate ping command.
    if system == "windows":
        # -n count, -w timeout in ms
        cmd = ["ping", "-n", str(count), "-w", str(timeout_seconds * 1000), host]
    elif system == "darwin":
        # macOS: -c count, -W timeout in ms (for each packet)
        cmd = ["ping", "-c", str(count), "-W", str(timeout_seconds * 1000), host]
    else:
        # Linux: -c count, -W timeout in seconds (per reply)
        cmd = ["ping", "-c", str(count), "-W", str(timeout_seconds), host]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(5, (count * timeout_seconds) + 5),
            check=False,
        )
    except FileNotFoundError:
        return "Error: ping command not found on the server running this tool."
    except subprocess.TimeoutExpired:
        return "Error: ping command timed out."
    except Exception as e:
        return f"Error: failed to run ping: {e}"

    output = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()

    combined = output
    if err:
        combined = (combined + "\n" + err).strip()

    if not combined:
        return f"Ping completed with exit code {proc.returncode}, but no output was captured."

    lines = combined.splitlines()

    # Keep the output readable: show the first few lines and the summary-like tail.
    head = lines[:8]
    tail = lines[-8:] if len(lines) > 8 else []

    result_lines = [f"Ping target: {host}", f"Exit code: {proc.returncode}", "", "--- Output (truncated) ---"]
    result_lines.extend(head)
    if tail and tail != head:
        result_lines.append("...")
        result_lines.extend(tail)

    return "\n".join(result_lines)
