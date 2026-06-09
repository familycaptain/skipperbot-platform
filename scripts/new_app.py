"""
new_app.py — Scaffold a new skipperbot-app-<name> repo.

Creates a sibling directory `../skipperbot-app-<name>/` with the standard
app skeleton.

Usage:
    python scripts/new_app.py

This script is interactive and will ask for the app display name and the
folder name to use. The folder name default is `skipperbot-app-<name>` in
lowercase, but any valid directory name is acceptable.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def slugify(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^\w\s-]", "", value)
    value = value.strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    return value


def component_name(value: str) -> str:
    parts = re.split(r"[\s_-]+", value.strip())
    return "".join(part.capitalize() for part in parts if part)


def prompt(text: str, default: str | None = None) -> str:
    prompt_text = f"{text}"
    if default:
        prompt_text += f" [{default}]"
    prompt_text += ": "
    answer = input(prompt_text).strip()
    return answer or (default or "")


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_app_skeleton(app_name: str, folder_name: str) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    target_dir = Path(folder_name)
    if not target_dir.is_absolute():
        target_dir = (repo_root.parent / target_dir).resolve()

    if target_dir.exists():
        raise FileExistsError(f"Destination already exists: {target_dir}")

    app_id = Path(folder_name).name
    if app_id.startswith("skipperbot-app-"):
        app_id = app_id[len("skipperbot-app-"):]
    app_id = slugify(app_id) or slugify(app_name)
    if not app_id:
        raise ValueError("Unable to determine a valid app id.")

    app_dir = target_dir
    ui_component = component_name(app_name)
    table_name = app_id.replace("-", "_")
    app_description = f"A new Skipperbot app that provides {app_name}."

    write_file(app_dir / "manifest.yaml", f"""id: {app_id}
name: {app_name}
description: {app_description}
core: false
package: false
web: true
requires: []
""")

    write_file(app_dir / "data.py", f"""from __future__ import annotations

from typing import Any

APP_ID = "{app_id}"


def digest_record(record: dict[str, Any]) -> dict[str, Any]:
    '''Convert an app record into a searchable memory digest.'''
    return {{
        "title": record.get("title") or f"{app_name} record",
        "text": str(record),
        "source": APP_ID,
    }}
""")

    write_file(app_dir / "tools.py", f"""from __future__ import annotations

from typing import Any


def example_tool(params: dict[str, Any]) -> str:
    '''A placeholder tool for the {app_name} app.'''
    return "This is a placeholder response from the {app_name} tool."
""")

    write_file(app_dir / "routes.py", f"""from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/{app_id}", tags=["{app_name}"])


@router.get("/")
async def root() -> dict[str, str]:
    return {{"message": "Hello from {app_name}!"}}
""")

    write_file(app_dir / "handlers.py", f"""from __future__ import annotations


def handle_event(event_name: str, payload: dict[str, object]) -> None:
    '''Handle subscribed events for the {app_name} app.'''
    print(f"Received event: {{event_name}}")
""")

    write_file(app_dir / "guide.md", f"""# {app_name}

This guide describes the {app_name} app to the Skipper agent.

## What it does

- Placeholder description for the {app_name} app.

## Tools

- `example_tool` — returns a placeholder response.
""")

    write_file(app_dir / "migrations/001_initial.sql", f"""-- Initial schema for {app_name}
CREATE TABLE IF NOT EXISTS {table_name}_items (
    id serial PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);
""")

    write_file(app_dir / "ui/index.js", f"""import React from \"react\";
import {{ createRoot }} from \"react-dom/client\";
import {{ {ui_component}App }} from \"./{ui_component}App.jsx\";

const root = document.getElementById(\"root\");
if (root) {{
  createRoot(root).render(<{ui_component}App />);
}}
""")

    write_file(app_dir / f"ui/{ui_component}App.jsx", f"""import React from \"react\";

export function {ui_component}App() {{
  return (
    <div>
      <h1>{app_name}</h1>
      <p>This is the starter UI for the {app_name} app.</p>
    </div>
  );
}}
""")

    write_file(app_dir / "specs/SPEC.md", f"""# {app_name} app spec

Describe the {app_name} app here.

## Entity types

- item

## Tools

- example_tool
""")

    source_app_packages = repo_root / "specs" / "APP_PACKAGES.md"
    if source_app_packages.exists():
        write_file(app_dir / "specs/APP_PACKAGES.md", source_app_packages.read_text(encoding="utf-8"))
    else:
        write_file(app_dir / "specs/APP_PACKAGES.md", "# APP_PACKAGES.md\n\nCopy the canonical APP_PACKAGES.md here.\n")

    write_file(app_dir / "README.md", f"""# {app_name}

A starter Skipperbot app scaffolded by scripts/new_app.py.

## Getting started

- Add your app to the Skipper platform loader.
- Implement your app logic in `tools.py`, `data.py`, and `handlers.py`.
- Customize the UI in `ui/{ui_component}App.jsx`.
""")

    write_file(app_dir / "LICENSE", "MIT License\n")

    write_file(app_dir / ".gitignore", "__pycache__/\nnode_modules/\n.env\n")

    write_file(app_dir / "pyproject.toml", f"""[project]
name = \"{folder_name}\"
version = \"0.1.0\"
description = \"A Skipperbot app.\"
authors = [\"Unknown <unknown@example.com>\"]
readme = \"README.md\"
requires-python = \">=3.12\"

[project.dependencies]
fastapi = "*"
""")

    write_file(app_dir / "tests/test_smoke.py", f"""def test_smoke() -> None:
    assert True
""")

    print(f"Created new app scaffold at: {app_dir}")
    print("Next steps:")
    print(f"  1. cd {app_dir}")
    print("  2. Review and customize the generated files.")
    print("  3. Add the app to your platform loader or docs as needed.")


def main() -> int:
    print("Skipperbot app scaffold generator")

    app_name = ""
    while not app_name.strip():
        app_name = prompt("App display name (proper case)")
        if not app_name.strip():
            print("App name cannot be empty.")

    default_folder = f"skipperbot-app-{slugify(app_name)}"
    folder_name = prompt(
        "App folder name",
        default_folder,
    )
    folder_name = folder_name.strip() or default_folder

    try:
        create_app_skeleton(app_name, folder_name)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to create app scaffold: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
