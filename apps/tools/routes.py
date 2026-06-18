"""Tools — FastAPI routes.

Mounted by the platform loader at ``/api/apps/tools``. Backs the
ToolsApp UI directly.

Endpoints (relative to the prefix above)::

    GET    /categories            — flattened tool registry
    GET    /guide/{guide_name}    — read a guide markdown file
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


def _platform_root() -> Path:
    # apps/tools/routes.py → apps/tools → apps → repo root
    return Path(__file__).resolve().parent.parent.parent


def _resolvable_guide(root: Path, key: str, cat: dict):
    """Compute the public, "/"-free guide *name* for a category.

    The returned value is one that ``GET /guide/{name}`` can resolve, or
    ``None`` when no guide file exists. It is NEVER the internal absolute
    ``_guide_path`` (which stays in the registry untouched for prompt
    injection) and never contains a "/".

    Derivation is per-category from the category's own identity:

    * PACKAGED (key starts with ``"app:"``): the bare app id, IFF
      ``apps/<app_id>/guide.md`` exists on disk; else ``None``.
    * LEGACY (bare key, from tool_routes.json): its declared ``guide``
      value returned verbatim (already a "/"-free ``*.md`` name), IFF
      ``prompts/guides/<value>`` exists on disk; else ``None``.
    """
    if key.startswith("app:"):
        app_id = key[len("app:"):]
        if app_id and "/" not in app_id and (root / "apps" / app_id / "guide.md").is_file():
            return app_id
        return None

    declared = cat.get("guide")
    if not declared or "/" in declared or "\\" in declared:
        return None
    if (root / "prompts" / "guides" / declared).is_file():
        return declared
    return None


@router.get("/categories")
async def api_tool_categories():
    """Return every tool category — both the legacy
    ``tool_routes.json`` entries (anything not yet packaged) and the
    categories declared by loaded app packages
    (``tool_router.TOOL_CATEGORIES``).

    The merged view lets the UI render a single browsable list
    without the user caring whether a category is legacy or
    packaged.
    """
    def _load():
        root = _platform_root()
        merged: dict[str, dict] = {}

        # Legacy tool_routes.json — first so app packages can override.
        routes_path = root / "tool_routes.json"
        if routes_path.is_file():
            with open(routes_path, "r", encoding="utf-8") as f:
                legacy = json.load(f)
            for key, cat in legacy.items():
                merged[key] = {
                    "id": key,
                    "description": cat.get("description", ""),
                    "tools": cat.get("tools", []),
                    "guide": _resolvable_guide(root, key, cat),
                    "keywords": cat.get("keywords", []),
                }

        # App-package categories — pull from the runtime registry so
        # this stays in sync with whatever the loader actually loaded.
        try:
            from tool_router import TOOL_CATEGORIES
            for key, cat in TOOL_CATEGORIES.items():
                # Loader keys packaged categories as "app:<id>".
                merged[key] = {
                    "id": key,
                    "description": cat.get("description", ""),
                    "tools": cat.get("tools", []),
                    "guide": _resolvable_guide(root, key, cat),
                    "keywords": cat.get("keywords", []),
                }
        except Exception as exc:
            logger.warning("tools/categories: could not read TOOL_CATEGORIES: %s", exc)

        categories = sorted(merged.values(), key=lambda c: c["id"])
        return {"categories": categories, "count": len(categories)}

    return await asyncio.to_thread(_load)


@router.get("/guide/{guide_name:path}")
async def api_tool_guide(guide_name: str):
    """Read a tool guide markdown file by name.

    Resolution order:

    1. ``apps/<id>/guide.md`` — for packaged apps.
    2. ``prompts/guides/<name>`` — legacy path (still used by apps
       that haven't been packaged).

    Path traversal (``..``, leading slashes, backslashes) is rejected.
    """
    if "/" in guide_name or "\\" in guide_name or ".." in guide_name:
        raise HTTPException(status_code=400, detail="Invalid guide name")

    root = _platform_root()

    # Packaged-app guide first. Drop a trailing .md if the caller already
    # supplied one so both forms work.
    bare = guide_name[:-3] if guide_name.endswith(".md") else guide_name
    packaged = root / "apps" / bare / "guide.md"
    if packaged.is_file():
        def _read_packaged():
            return packaged.read_text(encoding="utf-8")
        content = await asyncio.to_thread(_read_packaged)
        return {"name": guide_name, "content": content, "source": f"apps/{bare}/guide.md"}

    # Legacy prompts/guides location.
    legacy_name = guide_name if guide_name.endswith(".md") else f"{guide_name}.md"
    legacy = root / "prompts" / "guides" / legacy_name
    if legacy.is_file():
        def _read_legacy():
            return legacy.read_text(encoding="utf-8")
        content = await asyncio.to_thread(_read_legacy)
        return {"name": guide_name, "content": content, "source": f"prompts/guides/{legacy_name}"}

    raise HTTPException(status_code=404, detail=f"Guide '{guide_name}' not found")
