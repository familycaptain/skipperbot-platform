import os
from dotenv import load_dotenv
load_dotenv()


def get_guide(name: str = "") -> str:
    """Get a behavioral guide by name, or list all available guides.

    Guides contain detailed instructions for how to use specific tool categories
    (reminders, goals, lists, web/git, knowledge, etc.).

    Args:
        name: Guide name without extension (e.g. "web", "reminders", "goals").
            Leave empty to see the full index of all available guides.

    Returns:
        The guide content, or the guide index if no name is given.

    Ack: Loading guide...
    """
    try:
        app_root = os.path.abspath(os.getcwd())
        guides_dir = os.path.join(app_root, "prompts", "guides")

        if not name or not name.strip():
            # Return the index
            index_path = os.path.join(guides_dir, "INDEX.md")
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            # Fallback: list files
            files = sorted(f for f in os.listdir(guides_dir) if f.endswith(".md") and f != "INDEX.md")
            return "Available guides:\n" + "\n".join(f"- {f.replace('.md', '')}" for f in files)

        # Normalize name
        guide_name = name.strip().lower().replace(" ", "_")
        if not guide_name.endswith(".md"):
            guide_name += ".md"

        guide_path = os.path.join(guides_dir, guide_name)

        # Safety: stay in guides_dir
        if not os.path.abspath(guide_path).startswith(guides_dir):
            return "Error: invalid guide name"

        if not os.path.exists(guide_path):
            files = sorted(f.replace(".md", "") for f in os.listdir(guides_dir) if f.endswith(".md") and f != "INDEX.md")
            return f"Guide '{name}' not found. Available: {', '.join(files)}"

        with open(guide_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    except Exception as e:
        return f"Error in get_guide: {str(e)}"
