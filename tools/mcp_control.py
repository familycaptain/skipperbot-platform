"""
MCP Control - Restart and manage the MCP server
"""

import os
import subprocess
import signal

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = os.path.join(BASE_DIR, "mcp_server.pid")


def restart_mcp_server() -> str:
    """
    Restart the MCP subprocess only — NOT the main Skipper agent.
    Use this ONLY after creating or modifying tool files to reload them.
    Do NOT use this when the user says "restart yourself", "restart the server",
    or "restart Skipper" — use restart_agent for that instead.

    Returns:
        Success message or error description
    """
    try:
        stop_result = stop_mcp_server()
        start_result = start_mcp_server()
        return f"{stop_result}\n{start_result}"
    except Exception as e:
        return f"Error restarting MCP server: {str(e)}"


def start_mcp_server() -> str:
    """
    Start the MCP server as a background process.
    
    Returns:
        Success message with PID or error description
    """
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r', encoding='utf-8') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                return f"MCP server already running with PID {pid}"
            except OSError:
                pass
        
        process = subprocess.Popen(
            ["python3", "mcp_server.py"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        with open(PID_FILE, 'w', encoding='utf-8') as f:
            f.write(str(process.pid))
        
        return f"MCP server started with PID {process.pid}"
    except Exception as e:
        return f"Error starting MCP server: {str(e)}"


def stop_mcp_server() -> str:
    """
    Stop the running MCP server.
    
    Returns:
        Success message or error description
    """
    try:
        if not os.path.exists(PID_FILE):
            return "No MCP server PID file found. Server may not be running."
        
        with open(PID_FILE, 'r', encoding='utf-8') as f:
            pid = int(f.read().strip())
        
        try:
            os.kill(pid, signal.SIGTERM)
            os.remove(PID_FILE)
            return f"MCP server (PID {pid}) stopped."
        except OSError as e:
            os.remove(PID_FILE)
            return f"MCP server (PID {pid}) was not running. Cleaned up PID file."
    except Exception as e:
        return f"Error stopping MCP server: {str(e)}"


def mcp_server_status() -> str:
    """
    Check if the MCP server is running.
    
    Returns:
        Status message
    """
    try:
        if not os.path.exists(PID_FILE):
            return "MCP server status: Not running (no PID file)"
        
        with open(PID_FILE, 'r', encoding='utf-8') as f:
            pid = int(f.read().strip())
        
        try:
            os.kill(pid, 0)
            return f"MCP server status: Running (PID {pid})"
        except OSError:
            return f"MCP server status: Not running (stale PID {pid})"
    except Exception as e:
        return f"Error checking MCP server status: {str(e)}"
