"""App Help Tools.

Let the agent answer "what apps do I have?" and "how do I use the <X> app?" by
listing the installed apps and reading their user-facing help docs (help.md).
Used during onboarding (Skipper walks the user through each app) and any time a
user asks about an app. See BEHAVIOR.md for when to call these.
"""

from __future__ import annotations

from pathlib import Path

_APPS_DIR = Path(__file__).resolve().parent.parent / "apps"


def list_installed_apps() -> str:
    """List the apps installed in this Skipper, each with a one-line description.

    Use this when the user asks what apps or features are available, what Skipper
    can do, or which apps they have. Pair with get_app_help to explain one.

    Returns:
        A formatted list of installed apps ("Name — description").
    """
    try:
        from app_platform.loader import get_loaded_apps
        apps = get_loaded_apps()
    except Exception as e:  # noqa: BLE001
        return f"Could not list apps: {e}"
    if not apps:
        return "No apps are currently loaded."
    lines = ["Installed apps:"]
    for m in sorted(apps.values(), key=lambda a: (a.name or a.id).lower()):
        desc = (getattr(m, "description", "") or "").strip().replace("\n", " ")
        lines.append(f"- {m.name or m.id}" + (f" — {desc}" if desc else ""))
    return "\n".join(lines)


def get_app_help(app: str) -> str:
    """Get the user-facing help documentation for an installed app.

    Use this to answer "how do I use the <X> app?", "what does <X> do?", or to
    walk a user through an app during onboarding. Returns the app's help.md.

    Args:
        app: The app's id or name (e.g. "recipes" or "Recipes"). Case-insensitive.

    Returns:
        The app's help text (markdown), or a note if the app / its help doc isn't found.
    """
    try:
        from app_platform.loader import get_loaded_apps
        apps = get_loaded_apps()
    except Exception as e:  # noqa: BLE001
        return f"Could not look up apps: {e}"
    q = (app or "").strip().lower()
    if not q:
        return "Which app? Provide an app id or name (see list_installed_apps)."

    # Resolve by exact id/name first, then a loose contains-match.
    match = next((m for m in apps.values() if m.id.lower() == q or (m.name or "").lower() == q), None)
    if not match:
        match = next((m for m in apps.values() if q in m.id.lower() or q in (m.name or "").lower()), None)
    if not match:
        return f"No installed app matches '{app}'. Use list_installed_apps to see what's available."

    help_path = _APPS_DIR / match.id / "help.md"
    if help_path.is_file():
        try:
            text = help_path.read_text(encoding="utf-8").strip()
            if text:
                return f"# {match.name or match.id} — Help\n\n{text}"
        except Exception:  # noqa: BLE001
            pass
    desc = (getattr(match, "description", "") or "").strip()
    return (f"The {match.name or match.id} app doesn't have a detailed help doc yet."
            + (f" In short: {desc}" if desc else ""))
