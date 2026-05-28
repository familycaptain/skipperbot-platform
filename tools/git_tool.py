import os
from dotenv import load_dotenv
load_dotenv()

import subprocess
from typing import Optional, List


def git_tool(
    repo_path: str = ".",
    operation: str = "status",
    args: str = "",
    message: str = "",
    allow_network: bool = False,
) -> str:
    """Run a safe subset of Git operations on allowed repositories.

    Two sandbox zones:
    - The application root (skipperbot) — already a git repo. Use repo_path="." (default).
    - The repos base directory (REPOS_BASE_DIR from .env) — for cloning and working on
      external repos. Use repo_path="<repo_name>" to target a repo there.

    Clone operations ALWAYS create repos under REPOS_BASE_DIR, never inside the app root.
    Other operations work in either zone depending on repo_path.

    Security model:
    - Paths must resolve inside app_root or REPOS_BASE_DIR. Everything else is blocked.
    - Destructive operations (reset --hard, clean -fdx, rebase, etc.) are blocked.
    - Network operations (clone/pull/push/fetch) require allow_network=True.

    Args:
        repo_path: For clone: target directory name under REPOS_BASE_DIR (e.g. "my-project").
            For other ops: "." for the app repo, or a repo name under REPOS_BASE_DIR.
        operation: Git operation to run. One of: status, diff, log, branch, show, remote,
            checkout, add, commit, pull, push, fetch, clone.
        args: Extra arguments string for the chosen operation (space-delimited). Unsafe flags will be rejected.
        message: Commit message (used only when operation='commit').
        allow_network: If True, permits network operations (clone/pull/push/fetch). Default False.

    Returns:
        Formatted output of the git command, or a readable error.

    Ack: Running git {operation}...
    """
    try:
        app_root = os.path.abspath(os.getcwd())
        repos_base = os.getenv("REPOS_BASE_DIR", "").strip()
        if not repos_base:
            return "Error in git_tool: REPOS_BASE_DIR is not set in .env"
        repos_base = os.path.abspath(repos_base)

        def _is_in_zone(path: str) -> bool:
            """Check if path is inside app_root or repos_base."""
            return (
                path == app_root
                or path.startswith(app_root + os.sep)
                or path == repos_base
                or path.startswith(repos_base + os.sep)
            )

        def _resolve_path(rel: str, force_repos_base: bool = False) -> str:
            """Resolve repo_path to an absolute path in an allowed zone."""
            rel = rel.strip() or "."
            if os.path.isabs(rel):
                raise ValueError("repo_path must be relative, not absolute")
            # '.' or paths starting with '.' resolve relative to app_root
            if not force_repos_base and (rel == "." or rel.startswith("./")):
                candidate = os.path.abspath(os.path.join(app_root, rel))
            else:
                # Everything else resolves under repos_base
                candidate = os.path.abspath(os.path.join(repos_base, rel))
            if not _is_in_zone(candidate):
                raise ValueError(f"repo_path resolves outside allowed zones: {candidate}")
            return candidate

        op = (operation or "").strip().lower()
        allowed_ops = {
            "status",
            "diff",
            "log",
            "branch",
            "show",
            "remote",
            "checkout",
            "add",
            "commit",
            "pull",
            "push",
            "fetch",
            "clone",
        }
        if op not in allowed_ops:
            return (
                "Error in git_tool: unsupported operation. "
                "Allowed: status, diff, log, branch, show, remote, checkout, add, commit, pull, push, fetch, clone"
            )

        network_ops = {"clone", "pull", "push", "fetch"}
        if op in network_ops and not allow_network:
            return (
                "Blocked: network git operation requires allow_network=True. "
                "(clone/pull/push/fetch are disabled by default)"
            )

        extra = (args or "").strip()
        extra_parts: List[str] = extra.split() if extra else []

        # Block clearly dangerous flags/subcommands
        blocked_tokens = {
            "--hard",
            "--force",
            "-f",
            "--delete",
            "-d",
            "-D",
            "reset",
            "clean",
            "rebase",
            "filter-branch",
            "gc",
            "prune",
            "--prune",
            "stash",
            "worktree",
            "submodule",
            "config",
            "credential",
            "fsck",
        }
        for tok in extra_parts:
            if tok in blocked_tokens:
                return f"Blocked: unsafe git argument/token detected: {tok}"
            if ".." in tok:
                return "Blocked: path traversal token '..' is not allowed in args"

        def _run(cmd: List[str], cwd: Optional[str] = None) -> str:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
                env={
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                },
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            combined = "\n".join([s for s in [out, err] if s])
            if proc.returncode != 0:
                return f"git exited with code {proc.returncode}\n{combined}".strip()
            return combined or "(no output)"

        if op == "clone":
            # Clone always goes to repos_base
            if not extra_parts:
                return "Error in git_tool: clone requires args starting with the repo URL"
            url = extra_parts[0]
            remaining_args = extra_parts[1:]  # any extra clone flags
            if not (url.startswith("http://") or url.startswith("https://") or url.startswith("git@")):
                return "Blocked: clone URL must be http(s) or git@ style"

            target_dir = _resolve_path(repo_path, force_repos_base=True)
            os.makedirs(repos_base, exist_ok=True)

            if os.path.exists(target_dir) and os.listdir(target_dir):
                return "Blocked: target clone directory exists and is not empty"

            cmd = ["git", "clone"] + [url] + remaining_args + [target_dir]
            return f"$ {' '.join(cmd)}\n" + _run(cmd, cwd=repos_base)

        # Non-clone operations
        repo_abs = _resolve_path(repo_path)
        if not os.path.isdir(repo_abs):
            return f"Error in git_tool: repo_path does not exist: {repo_path}"

        cmd: List[str] = ["git", op]

        if op == "commit":
            if not message.strip():
                return "Error in git_tool: commit requires a non-empty message"
            cmd += ["-m", message.strip()]
            cmd += extra_parts
        else:
            cmd += extra_parts

        return f"$ {' '.join(cmd)} (cwd={repo_path})\n" + _run(cmd, cwd=repo_abs)

    except subprocess.TimeoutExpired:
        return "Error in git_tool: git command timed out"
    except Exception as e:
        return f"Error in git_tool: {str(e)}"