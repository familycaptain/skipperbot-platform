"""
new_app.py — Scaffold a new skipperbot-app-<name> repo.

Creates a sibling directory `../skipperbot-app-<name>/` with the standard
app skeleton that satisfies the platform's app contract (see
`specs/APP_PACKAGES.md`).

Usage:
    python scripts/new_app.py

This script is interactive and asks for the app display name and the folder
name to use. The folder name default is `skipperbot-app-<name>` in lowercase,
but any valid directory name is acceptable.

The generated app is wired to load correctly when its folder is dropped into a
platform's `apps/<id>/` directory: the data layer calls `digest_record` on
every mutation, `ui/index.js` exports the launcher registry array, `routes.py`
uses a bare router (the loader mounts it at `/api/apps/<id>/`), and the package
ships an `__init__.py` so intra-app imports (`from apps.<id> import data`)
resolve.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def slugify(value: str) -> str:
    """Hyphenated, lowercase slug — used for the sibling repo folder name."""
    value = value.strip()
    value = re.sub(r"[^\w\s-]", "", value)
    value = value.strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    return value


def identifier(value: str) -> str:
    """Postgres- and Python-safe app id.

    The id is used both as the Postgres schema (``app_<id>``) and the Python
    package (``apps.<id>``), so it must be a lowercase identifier: letters,
    digits and underscores only, not starting with a digit.
    """
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    if value and value[0].isdigit():
        value = f"app_{value}"
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


def render(template: str, tokens: dict[str, str]) -> str:
    out = template
    for key, val in tokens.items():
        out = out.replace(key, val)
    return out


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Templates (plain strings; placeholders like __APP_ID__ are substituted)
# ---------------------------------------------------------------------------

MANIFEST = """id: __APP_ID__
name: "__APP_NAME__"
version: "0.1.0"
description: "__DESC__"

# core: true marks a platform-required app (the platform refuses to boot
# without it). Optional apps that live in their own repo stay false.
core: false

# Platform services this app uses (documentation / intent; not enforced).
platform_deps: []

# Entity types this app owns. Pick a SHORT, GLOBALLY-UNIQUE prefix (2-4 chars).
# The platform auto-registers these so the entities are linkable from chat.
entity_types:
  - prefix: __PREFIX__
    name: __APP_NAME__ item
    id_format: "__PREFIX__-{hex8}"
    table: items

# Routes chat to this app's tools. Tune the keywords to what users actually say.
# Set to `null` only for a UI-only app whose chat tools live at platform level.
tool_category:
  description: "__DESC__"
  keywords:
    - __APP_ID__

# Events this app emits / subscribes to (see app_platform.events).
emits: []
subscribes: []

# Desktop UI registrations — keep in sync with ui/index.js.
ui:
  apps:
    - id: __APP_ID__
      name: __APP_NAME__
      icon: LayoutGrid
      component: __COMPONENT__App
      singleton: true

# Background job handlers (optional): {type, handler: "handlers.fn", max_concurrent}.
job_types: []

# Per-app settings shown in the toolbar cog wheel (optional).
config: []
"""

INIT = '"""__APP_NAME__ app package — discovered and loaded by app_platform.loader."""\n'

DATA = '''"""Data layer for the __APP_NAME__ app.

All tables live in the per-app Postgres schema (``__SCHEMA__``). The platform
sets search_path to that schema + public, so this module uses unqualified
table names.

Every mutation calls ``digest_record`` so chat can recall these entities later
(required by the app contract — see specs/APP_PACKAGES.md).
"""
from __future__ import annotations

import secrets

from app_platform.db import (
    execute_in_schema,
    execute_returning_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
)
from app_platform.memory import digest_record

APP_ID = "__APP_ID__"
SCHEMA = "__SCHEMA__"

# Tells chat which attributes matter most when recalling this entity later.
# Make it specific — vague hints produce useless memories.
_ITEM_HINT = (
    "Focus on: the item's title and notes. These memories are how chat "
    "recalls which __APP_NAME__ item the user means."
)


def _new_id() -> str:
    return f"__PREFIX__-{secrets.token_hex(4)}"


def _row(row: dict | None) -> dict | None:
    return dict(row) if row else None


def create_item(title: str, notes: str = "", by: str = "") -> dict | None:
    """Create an item and digest it into semantic memory."""
    item = _row(execute_returning_in_schema(
        SCHEMA,
        "INSERT INTO items (id, title, notes, created_by) "
        "VALUES (%s, %s, %s, %s) RETURNING *",
        (_new_id(), title, notes, by),
    ))
    if item:
        digest_record(app_id=APP_ID, entity_type="item", action="created",
                      entity_id=item["id"], record=item, by=by,
                      context_hint=_ITEM_HINT)
    return item


def get_item(item_id: str) -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA, "SELECT * FROM items WHERE id = %s", (item_id,)))


def list_items(limit: int = 100) -> list[dict]:
    return fetch_all_in_schema(
        SCHEMA, "SELECT * FROM items ORDER BY created_at DESC LIMIT %s", (limit,))


def update_item(item_id: str, by: str = "", **fields) -> dict | None:
    """Update mutable columns and re-digest."""
    allowed = {k: v for k, v in fields.items() if k in ("title", "notes")}
    if allowed:
        sets = ", ".join(f"{k} = %s" for k in allowed)
        execute_in_schema(
            SCHEMA,
            f"UPDATE items SET {sets}, updated_at = now() WHERE id = %s",
            (*allowed.values(), item_id),
        )
    item = get_item(item_id)
    if item:
        digest_record(app_id=APP_ID, entity_type="item", action="updated",
                      entity_id=item["id"], record=item, by=by,
                      context_hint=_ITEM_HINT)
    return item


def delete_item(item_id: str, by: str = "") -> bool:
    item = get_item(item_id)          # fetch BEFORE deleting so we can digest it
    ok = execute_in_schema(
        SCHEMA, "DELETE FROM items WHERE id = %s", (item_id,)) > 0
    if ok and item:
        digest_record(app_id=APP_ID, entity_type="item", action="deleted",
                      entity_id=item_id, record=item, by=by)
    return ok


# Consumed by the platform's memory backfill script to seed memories for rows
# that existed before the digest wiring (or after a bulk import).
BACKFILL_ENTITIES = [
    {"entity_type": "item", "list_fn": list_items, "context_hint": _ITEM_HINT},
]
'''

TOOLS = '''"""MCP / chat tools for the __APP_NAME__ app.

Every PUBLIC function here becomes a chat tool — the platform turns the
docstring into the tool schema. Keep helpers underscore-prefixed so they are
NOT registered. Tool names must be globally unique across installed apps, so
they are namespaced with the app id.

Maintain UI <-> chat parity: anything the UI can do must be doable through one
of these tools.
"""
from __future__ import annotations

from apps.__APP_ID__ import data as _dl


def __CREATE_FN__(title: str, notes: str = "", by: str = "") -> str:
    """Create a new __APP_NAME__ item with a title and optional notes."""
    item = _dl.create_item(title=title, notes=notes, by=by)
    if not item:
        return "Could not create the item."
    return f"Created {item['id']}: {item['title']}"


def __LIST_FN__() -> str:
    """List the __APP_NAME__ items."""
    items = _dl.list_items()
    if not items:
        return "No items yet."
    return "\\n".join(f"- {i['id']}: {i['title']}" for i in items)
'''

ROUTES = '''"""REST routes for the __APP_NAME__ app.

The platform mounts this router at /api/apps/__APP_ID__/ — do NOT set a prefix
here, or the paths would be doubled.
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.__APP_ID__ import data as _dl

router = APIRouter()


@router.get("/")
async def list_items():
    return {"items": _dl.list_items()}


@router.get("/{item_id}")
async def get_item(item_id: str):
    return _dl.get_item(item_id)
'''

HANDLERS = '''"""Optional event subscribers and job handlers for the __APP_NAME__ app.

The loader imports this module on startup and wires any @subscribe decorators
automatically. Job handlers are referenced from manifest.yaml under job_types.
Uncomment and adapt as needed.
"""
from __future__ import annotations

# from app_platform.events import subscribe
#
# @subscribe("entity.linked")
# def on_linked(event: dict) -> None:
#     ...
#
# async def handle_example_job(job: dict, ctx) -> str:
#     """manifest.yaml -> job_types[].handler = "handlers.handle_example_job"."""
#     return "done"
'''

GUIDE = """# __APP_NAME__

Agent-facing guide: when and how the Skipper agent should use the __APP_NAME__
app's tools. (The user-facing manual is help.md — keep them separate.)

## What it does

Briefly describe the domain this app owns.

## Tools

- `__CREATE_FN__` — create a new item.
- `__LIST_FN__` — list items.

## When to use it

Describe the kinds of user requests that should route here (mirror the
manifest `tool_category.keywords`).
"""

# User-facing manual. Shown in-app via the ? button and returned by the
# get_app_help chat tool. This is a real manual, not a blurb — flesh it out.
# See docs/app-help-authoring.md in the platform repo for the full structure.
HELP = """# __APP_NAME__

__APP_NAME__ for Skipperbot — a one-line summary of what it's for.

## Overview

What this app does and when you'd reach for it, in plain language (2-4 short
paragraphs).

## Screens

Walk through each screen/area of the UI: what's on it, what each control does,
and what the user sees.

## Example workflows

1. **Add an item** — open __APP_NAME__, ... (step-by-step).
2. **Find an item** — ... .

## Tips

- ...

## FAQ

- **Q:** ...  **A:** ...
"""

MIGRATION = """-- Initial schema for the __APP_NAME__ app.
-- Runs with search_path = __SCHEMA__, public — use unqualified table names.
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    created_by  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

UI_INDEX = """// UI manifest for the __APP_NAME__ app.
// Discovered by web/src/apps/registry.js via import.meta.glob at build time;
// each entry is auto-tagged with `appPackage: true`. This file MUST default-
// export the registry array — it is NOT a DOM entry point, so do not call
// createRoot() here. The platform shell mounts `component` for you.
import { lazy } from "react";
import { LayoutGrid } from "lucide-react";

export default [
  {
    id: "__APP_ID__",
    name: "__APP_NAME__",
    icon: LayoutGrid,
    component: lazy(() => import("./__COMPONENT__App")),
    singleton: true,
  },
];
"""

UI_APP = """import React, { useEffect, useState } from "react";

// The window shell mounts this in a fixed flex region. The root must be a
// full-size column flex container, or the layout breaks:
//   w-full     fill the window width
//   shrink-0   on fixed bars so they aren't squeezed
//   min-h-0    on the scroll area so overflow-y-auto engages
export default function __COMPONENT__App() {
  const [items, setItems] = useState([]);

  useEffect(() => {
    fetch("/api/apps/__APP_ID__/")
      .then((r) => r.json())
      .then((d) => setItems(d.items || []))
      .catch(() => setItems([]));
  }, []);

  return (
    // Semantic design-system classes only — NO raw Tailwind color scales (issue #38).
    // surface-page sets the themed background + text; see specs/APP_PACKAGES.md "Styling / Theme".
    <div className="flex flex-col h-full w-full surface-page">
      <div className="shrink-0 px-4 py-3 border-b border-subtle font-semibold">
        __APP_NAME__
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {items.length === 0 ? (
          <p className="empty-state">No items yet.</p>
        ) : (
          <ul className="space-y-1">
            {items.map((it) => (
              <li key={it.id}>{it.title}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
"""

import re as _re

# Raw color classes forbidden in scaffolded UI (issue #38) — see scripts/check-no-raw-tokens.mjs.
_RAW_UI = _re.compile(
    r"\b(?:bg|text|border|ring|from|to|via)-(?:slate|gray|zinc|neutral|stone|cyan|teal|sky)-\d{2,3}(?:/\d{1,3})?\b"
    r"|\b(?:bg|text)-(?:white|black)\b"
    r"|\b(?:bg|text|border)-\[#[0-9a-fA-F]{3,8}\]"
)


def _assert_semantic_ui(rendered_ui: str) -> None:
    hits = sorted({m.group(0) for m in _RAW_UI.finditer(rendered_ui)})
    if hits:
        raise SystemExit(
            "scaffold smoke check FAILED (#38): generated UI contains raw color classes: "
            + ", ".join(hits)
            + " — use semantic classes (surface-*/text-*/btn-*/…, see specs/APP_PACKAGES.md Styling/Theme)."
        )


SPEC = """# __APP_NAME__ — Spec

## Purpose

What this app is for and which domain it owns.

## Data Model

Schema: `__SCHEMA__`.

### `items`

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `__PREFIX__-{hex8}` |
| `title` | `text NOT NULL` | |
| `notes` | `text` | markdown |
| `created_by` | `text` | |
| `created_at` | `timestamptz` | |
| `updated_at` | `timestamptz` | |

## Entity types

| Prefix | Name | Table |
|---|---|---|
| `__PREFIX__` | item | `items` |

## Tools (UI <-> chat parity)

- `__CREATE_FN__`
- `__LIST_FN__`

## Events

Emits: none yet. Subscribes: none yet.
"""

README = """# __APP_NAME__

A Skipperbot optional app (`skipperbot-app-__APP_ID__`), scaffolded by
`scripts/new_app.py` in the platform repo.

## Layout

- `manifest.yaml` — how the platform discovers and wires the app.
- `__init__.py` — makes `apps.__APP_ID__` an importable package.
- `data.py` — data layer; calls `digest_record` on every mutation.
- `tools.py` — MCP / chat tools (UI <-> chat parity).
- `routes.py` — FastAPI router, mounted by the platform at `/api/apps/__APP_ID__/`.
- `handlers.py` — optional event subscribers / job handlers.
- `migrations/` — SQL (and optional Python) migrations for the `__SCHEMA__` schema.
- `ui/` — desktop React UI; `index.js` exports the launcher registry array.
- `guide.md` — agent-facing guide (how the agent drives the tools).
- `help.md` — user-facing manual (shown in-app; returned by `get_app_help`).
- `specs/` — this app's `SPEC.md` plus the canonical `APP_PACKAGES.md` contract.

## License

The platform is MIT, but this app is yours — release it under any license you
like, including a proprietary or commercial one. Edit `LICENSE` to choose.

## Install into a running platform

```bash
cd /path/to/skipperbot-platform/apps
git clone <this-repo-url> __APP_ID__   # folder name MUST equal the manifest id
cd ..
# Restart the platform (the web bundle rebuilds automatically).
# See docs/02-adding-apps.md in the platform repo.
```

On restart the loader creates the `__SCHEMA__` schema, runs migrations, and
registers the app's entity types, tools, routes, and UI.

## Build it out

Follow the authoring workflow in the platform repo's `docs/BUILDING_APPS.md` —
that's the human guide.

`specs/APP_PACKAGES.md` (shipped in this repo) is the **app contract**, written
as prompt guidance for an AI assistant. If you're building with AI, point it at
that file; you don't need to read it cover to cover. It defines the rules every
app must satisfy: memory digestion on every CRUD, notify via
`create_notification`, recurring work via schedules, UI <-> chat parity.
"""

PYPROJECT = """[project]
name = "__FOLDER__"
version = "0.1.0"
description = "A Skipperbot app."
readme = "README.md"
requires-python = ">=3.12"
authors = [{ name = "Your Name", email = "you@example.com" }]
# Apps run inside the platform and rely on its installed dependencies
# (fastapi, etc.). Only list deps your app adds on top.
dependencies = []
"""

GITIGNORE = "__pycache__/\nnode_modules/\n.env\n"

# Your app, your license. The Skipperbot platform is MIT, but a separately
# distributed app may use ANY license — including proprietary/commercial.
LICENSE = """Choose a license for this app.

This app is your own work. The Skipperbot platform is MIT-licensed, but your
app does NOT have to be — you may release it under any license you like,
including a proprietary or commercial one (e.g. a paid app with an EULA).

Replace this file with your chosen license text. Common choices:
  - MIT / Apache-2.0 / BSD  (permissive open source)
  - AGPL-3.0                (copyleft open source)
  - A proprietary EULA      (closed source / commercial)
"""

TEST_SMOKE = """def test_smoke() -> None:
    assert True
"""


def create_app_skeleton(app_name: str, folder_name: str) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    target_dir = Path(folder_name)
    if not target_dir.is_absolute():
        target_dir = (repo_root.parent / target_dir).resolve()

    if target_dir.exists():
        raise FileExistsError(f"Destination already exists: {target_dir}")

    # The installable app id (folder under apps/, schema name, python package)
    # must be a safe identifier. Derive it from the folder name, stripping the
    # conventional skipperbot-app- prefix, then fall back to the display name.
    raw_id = Path(folder_name).name
    if raw_id.startswith("skipperbot-app-"):
        raw_id = raw_id[len("skipperbot-app-"):]
    app_id = identifier(raw_id) or identifier(app_name)
    if not app_id:
        raise ValueError("Unable to determine a valid app id.")

    app_dir = target_dir
    component = component_name(app_name) or "App"
    prefix = re.sub(r"[^a-z0-9]", "", app_id)[:2] or "xx"
    schema = f"app_{app_id}"

    tokens = {
        "__APP_ID__": app_id,
        "__APP_NAME__": app_name,
        "__FOLDER__": Path(folder_name).name,
        "__COMPONENT__": component,
        "__PREFIX__": prefix,
        "__SCHEMA__": schema,
        "__DESC__": f"{app_name} for Skipperbot.",
        "__CREATE_FN__": f"create_{app_id}_item",
        "__LIST_FN__": f"list_{app_id}_items",
    }

    files = {
        "manifest.yaml": MANIFEST,
        "__init__.py": INIT,
        "data.py": DATA,
        "tools.py": TOOLS,
        "routes.py": ROUTES,
        "handlers.py": HANDLERS,
        "guide.md": GUIDE,
        "help.md": HELP,
        "migrations/001_initial.sql": MIGRATION,
        "ui/index.js": UI_INDEX,
        f"ui/{component}App.jsx": UI_APP,
        "specs/SPEC.md": SPEC,
        "README.md": README,
        "LICENSE": LICENSE,
        ".gitignore": GITIGNORE,
        "pyproject.toml": PYPROJECT,
        "tests/__init__.py": "",          # tests/ is a package so it's discoverable when mounted at apps/<id>/tests
        "tests/test_smoke.py": TEST_SMOKE,
    }

    for rel, template in files.items():
        write_file(app_dir / rel, render(template, tokens))

    # Scaffold smoke check (issue #38): the generated UI must use ONLY semantic
    # design-system classes — no raw Tailwind color scales / hex / white-black.
    _assert_semantic_ui(render(UI_APP, tokens))

    # Ship the canonical app contract alongside the app so the repo is
    # self-sufficient for AI-assisted development.
    source_app_packages = repo_root / "specs" / "APP_PACKAGES.md"
    if source_app_packages.exists():
        write_file(app_dir / "specs/APP_PACKAGES.md",
                   source_app_packages.read_text(encoding="utf-8"))
    else:
        write_file(app_dir / "specs/APP_PACKAGES.md",
                   "# APP_PACKAGES.md\n\nCopy the canonical APP_PACKAGES.md here.\n")

    print(f"Created new app scaffold at: {app_dir}")
    print(f"  app id     : {app_id}   (folder under apps/, schema {schema})")
    print(f"  entity     : prefix '{prefix}', table 'items'")
    print("Next steps:")
    print(f"  1. cd {app_dir}")
    print("  2. Read docs/BUILDING_APPS.md (in the platform repo) — the human")
    print("     authoring guide. Building with AI? Point it at specs/APP_PACKAGES.md")
    print("     (the contract), which is shipped in this app repo.")
    print("  3. Replace the 'items' placeholder entity with your real model")
    print("     (manifest entity_types, migrations, data.py, tools.py, UI).")
    print("  4. To test in a platform: clone/copy this folder into")
    print(f"     <platform>/apps/{app_id}/ and restart (see docs/02-adding-apps.md).")


def main() -> int:
    print("Skipperbot app scaffold generator")

    app_name = ""
    while not app_name.strip():
        app_name = prompt("App display name (proper case)")
        if not app_name.strip():
            print("App name cannot be empty.")

    default_folder = f"skipperbot-app-{slugify(app_name)}"
    folder_name = prompt("App folder name", default_folder)
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
