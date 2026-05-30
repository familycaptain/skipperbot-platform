"""List directory contents within the app root (sandboxed ls).

This tool is limited to listing files/directories under the application root
(the directory containing agent.py). It rejects any path that attempts to
escape the app root.
"""

import os
from dotenv import load_dotenv
load_dotenv()

import os
import stat
import datetime
from typing import List, Tuple

from app_platform.time import get_timezone


def ls_dir(path: str = ".",
           recursive: bool = False,
           max_depth: int = 2,
           show_hidden: bool = False,
           sort_by: str = "name",
           descending: bool = False,
           max_results: int = 200) -> str:
    """List directory contents within the app folder.

    Args:
        path: Directory path relative to the app root to list.
        recursive: If True, lists recursively (depth-limited).
        max_depth: Maximum recursion depth when recursive is True.
        show_hidden: If True, include dotfiles and dot-directories.
        sort_by: Sort key: 'name', 'mtime', or 'size'.
        descending: If True, sort in descending order.
        max_results: Maximum number of entries to return.

    Returns:
        A formatted listing similar to a simple 'ls -l', limited to the app root.
    """
    try:
        # Resolve app root (directory containing agent.py)
        app_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

        # Resolve target directory
        rel_path = path or "."
        # Disallow null bytes
        if "\x00" in rel_path:
            return "Error in ls_dir: invalid path"

        target = os.path.abspath(os.path.join(app_root, rel_path))

        # Enforce sandbox
        if not (target == app_root or target.startswith(app_root + os.sep)):
            return "Error in ls_dir: path escapes app root"

        if not os.path.exists(target):
            return f"Error in ls_dir: path does not exist: {path}"
        if not os.path.isdir(target):
            return f"Error in ls_dir: path is not a directory: {path}"

        if max_results < 1:
            max_results = 1
        if max_results > 2000:
            max_results = 2000

        if max_depth < 0:
            max_depth = 0
        if max_depth > 20:
            max_depth = 20

        sort_by_norm = (sort_by or "name").strip().lower()
        if sort_by_norm not in {"name", "mtime", "size"}:
            return "Error in ls_dir: sort_by must be one of: name, mtime, size"

        entries: List[Tuple[str, os.stat_result]] = []

        def should_include(name: str) -> bool:
            if show_hidden:
                return True
            return not name.startswith(".")

        def walk_dir(dir_path: str, depth: int) -> None:
            nonlocal entries
            try:
                with os.scandir(dir_path) as it:
                    for de in it:
                        if len(entries) >= max_results:
                            return
                        if not should_include(de.name):
                            continue
                        try:
                            st = de.stat(follow_symlinks=False)
                        except Exception:
                            # If stat fails, skip
                            continue

                        rel = os.path.relpath(de.path, app_root)
                        entries.append((rel, st))

                        if recursive and de.is_dir(follow_symlinks=False) and depth < max_depth:
                            walk_dir(de.path, depth + 1)
                        if len(entries) >= max_results:
                            return
            except PermissionError:
                # Skip unreadable directories
                return

        walk_dir(target, 0)

        def sort_key(item: Tuple[str, os.stat_result]):
            rel, st = item
            if sort_by_norm == "name":
                return rel.lower()
            if sort_by_norm == "mtime":
                return st.st_mtime
            return st.st_size

        entries.sort(key=sort_key, reverse=bool(descending))

        lines: List[str] = []
        header = f"Listing: {os.path.relpath(target, app_root)} (recursive={recursive}, max_depth={max_depth})"
        lines.append(header)
        lines.append("mode       size        mtime               path")
        lines.append("----       ----        ----                ----")

        for rel, st in entries:
            mode = stat.filemode(st.st_mode)
            size = st.st_size
            mtime = datetime.datetime.fromtimestamp(st.st_mtime, get_timezone()).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{mode:<10} {size:>10}  {mtime}  {rel}")

        if not entries:
            lines.append("(no entries)")

        if len(entries) >= max_results:
            lines.append(f"\n(note) results truncated at max_results={max_results}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error in ls_dir: {str(e)}"