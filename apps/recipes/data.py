"""Recipes Data Layer
====================
Postgres CRUD for recipes, categories, and recipe–image links.

Tables live in the app_recipes schema (migrated from public by 001_initial.sql).
Images are in the public schema and accessed via public.images in JOINs.
"""

import logging
from datetime import datetime, timezone

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
    scoped_conn,
)
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_recipes"

_RECIPE_HINT = (
    "Focus on: recipe title, main categories, brief description of the dish, "
    "key ingredients (names only, not quantities), prep and cook time, servings, "
    "rating, and any chef comments or notable notes."
)

# Fields that warrant a new memory when updated — skip cooking-session-only fields
_MEANINGFUL_FIELDS = {
    "title", "description", "ingredients", "steps",
    "prep_time_min", "cook_time_min", "servings", "categories",
    "source_url", "rating", "chef_comments", "notes",
}


# ---------------------------------------------------------------------------
# Schema-aware DB shortcuts
# ---------------------------------------------------------------------------

def _fetch_one(query, params=()):
    return fetch_one_in_schema(SCHEMA, query, params)


def _fetch_all(query, params=()):
    return fetch_all_in_schema(SCHEMA, query, params)


def _execute(query, params=()):
    return execute_in_schema(SCHEMA, query, params)


def _execute_returning(query, params=()):
    return execute_returning_in_schema(SCHEMA, query, params)


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------

def save_recipe(recipe: dict, by: str = ""):
    """Insert or update a recipe."""
    is_new = get_recipe(recipe["id"]) is None
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO recipes (id, title, description, ingredients, steps,
                                     prep_time_min, cook_time_min, servings, categories,
                                     source_url, rating, chef_comments, notes,
                                     checked_ingredients, last_opened_at,
                                     created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    ingredients = EXCLUDED.ingredients,
                    steps = EXCLUDED.steps,
                    prep_time_min = EXCLUDED.prep_time_min,
                    cook_time_min = EXCLUDED.cook_time_min,
                    servings = EXCLUDED.servings,
                    categories = EXCLUDED.categories,
                    source_url = EXCLUDED.source_url,
                    rating = EXCLUDED.rating,
                    chef_comments = EXCLUDED.chef_comments,
                    notes = EXCLUDED.notes,
                    checked_ingredients = EXCLUDED.checked_ingredients,
                    last_opened_at = EXCLUDED.last_opened_at,
                    updated_at = EXCLUDED.updated_at
            """, (
                recipe["id"],
                recipe.get("title", ""),
                recipe.get("description", ""),
                _json(recipe.get("ingredients", [])),
                _json(recipe.get("steps", [])),
                recipe.get("prep_time_min"),
                recipe.get("cook_time_min"),
                recipe.get("servings", 1),
                recipe.get("categories", []),
                recipe.get("source_url", ""),
                recipe.get("rating"),
                recipe.get("chef_comments", ""),
                recipe.get("notes", ""),
                recipe.get("checked_ingredients", []),
                recipe.get("last_opened_at"),
                recipe.get("created_by", ""),
                recipe.get("created_at", _now()),
                recipe.get("updated_at", _now()),
            ))
        conn.commit()
    saved = get_recipe(recipe["id"])
    if saved:
        digest_record(
            app_id="recipes",
            entity_type="recipe",
            action="created" if is_new else "updated",
            entity_id=recipe["id"],
            record=saved,
            by=by or recipe.get("created_by", ""),
            context_hint=_RECIPE_HINT,
        )


def get_recipe(recipe_id: str) -> dict | None:
    row = _fetch_one("SELECT * FROM recipes WHERE id = %s", (recipe_id,))
    return _recipe_row(row) if row else None


def get_all_recipes() -> list[dict]:
    return [_recipe_row(r) for r in _fetch_all(
        "SELECT * FROM recipes ORDER BY updated_at DESC"
    )]


def search_recipes(query: str) -> list[dict]:
    """Search recipes by title, description, or ingredient names."""
    pattern = f"%{query}%"
    rows = _fetch_all(
        """SELECT * FROM recipes
           WHERE title ILIKE %s OR description ILIKE %s
                 OR ingredients::text ILIKE %s
           ORDER BY updated_at DESC""",
        (pattern, pattern, pattern),
    )
    return [_recipe_row(r) for r in rows]


def filter_by_category(category: str) -> list[dict]:
    """Get recipes that have the given category."""
    rows = _fetch_all(
        "SELECT * FROM recipes WHERE %s = ANY(categories) ORDER BY updated_at DESC",
        (category,),
    )
    return [_recipe_row(r) for r in rows]


def update_recipe(recipe_id: str, updates: dict, by: str = "") -> bool:
    """Partial update — only set the provided fields."""
    allowed = {
        "title", "description", "ingredients", "steps",
        "prep_time_min", "cook_time_min", "servings", "categories",
        "source_url", "rating", "chef_comments", "notes",
        "checked_ingredients", "last_opened_at",
        "checked_steps",
    }
    sets = []
    vals = []
    has_checked_ingredients = False
    has_checked_steps = False
    for key, val in updates.items():
        if key not in allowed:
            continue
        if key in ("ingredients", "steps"):
            sets.append(f"{key} = %s::jsonb")
            vals.append(_json(val))
        else:
            sets.append(f"{key} = %s")
            vals.append(val)
        if key == "checked_ingredients":
            has_checked_ingredients = True
        if key == "checked_steps":
            has_checked_steps = True
    if not sets:
        return False
    if has_checked_ingredients:
        sets.append("checked_ingredients_at = %s")
        vals.append(_now())
    if has_checked_steps:
        sets.append("checked_steps_at = %s")
        vals.append(_now())
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(recipe_id)
    ok = _execute(
        f"UPDATE recipes SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok and updates.keys() & _MEANINGFUL_FIELDS:
        updated = get_recipe(recipe_id)
        if updated:
            digest_record(
                app_id="recipes",
                entity_type="recipe",
                action="updated",
                entity_id=recipe_id,
                record=updated,
                by=by,
                context_hint=_RECIPE_HINT,
            )
    return ok


def delete_recipe(recipe_id: str, by: str = "") -> bool:
    recipe = get_recipe(recipe_id)
    ok = _execute("DELETE FROM recipes WHERE id = %s", (recipe_id,)) > 0
    if ok and recipe:
        digest_record(
            app_id="recipes",
            entity_type="recipe",
            action="deleted",
            entity_id=recipe_id,
            record=recipe,
            by=by,
        )
    return ok


def touch_recipe(recipe_id: str):
    """Update last_opened_at to now."""
    _execute(
        "UPDATE recipes SET last_opened_at = %s WHERE id = %s",
        (_now(), recipe_id),
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def get_all_categories() -> list[dict]:
    return [_cat_row(r) for r in _fetch_all(
        "SELECT * FROM recipe_categories ORDER BY sort_order, name"
    )]


def get_all_categories_merged() -> list[dict]:
    """Return categories from the categories table plus any extra names
    found on recipes that aren't in the table yet."""
    table_cats = get_all_categories()
    known_names = {c["name"].lower() for c in table_cats}
    # Pull distinct category names embedded on recipes
    rows = _fetch_all(
        "SELECT DISTINCT unnest(categories) AS name FROM recipes ORDER BY name"
    )
    extras = []
    for r in rows:
        name = r["name"] if isinstance(r, dict) else r[0]
        if name and name.lower() not in known_names:
            extras.append({"id": f"_inline_{name}", "name": name, "sort_order": 9999})
            known_names.add(name.lower())
    return table_cats + extras


def create_category(cat_id: str, name: str) -> dict | None:
    return _cat_row(_execute_returning(
        """INSERT INTO recipe_categories (id, name, sort_order)
           VALUES (%s, %s, COALESCE((SELECT MAX(sort_order)+1 FROM recipe_categories), 0))
           RETURNING *""",
        (cat_id, name),
    ))


def update_category(cat_id: str, name: str) -> bool:
    return _execute(
        "UPDATE recipe_categories SET name = %s WHERE id = %s",
        (name, cat_id),
    ) > 0


def delete_category(cat_id: str) -> bool:
    return _execute("DELETE FROM recipe_categories WHERE id = %s", (cat_id,)) > 0


# ---------------------------------------------------------------------------
# Recipe–Image links
# ---------------------------------------------------------------------------

def get_recipe_images(recipe_id: str) -> list[dict]:
    """Get all images linked to a recipe, ordered by sort_order."""
    rows = _fetch_all(
        """SELECT i.*, ri.sort_order FROM public.images i
           JOIN recipe_images ri ON ri.image_id = i.id
           WHERE ri.recipe_id = %s
           ORDER BY ri.sort_order, i.created_at""",
        (recipe_id,),
    )
    return [_image_row(r) for r in rows]


def link_image(recipe_id: str, image_id: str, sort_order: int = 0):
    """Link an image to a recipe."""
    _execute(
        """INSERT INTO recipe_images (recipe_id, image_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (recipe_id, image_id, sort_order),
    )


def unlink_image(recipe_id: str, image_id: str):
    _execute(
        "DELETE FROM recipe_images WHERE recipe_id = %s AND image_id = %s",
        (recipe_id, image_id),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(obj) -> str:
    import json
    return json.dumps(obj)


def _recipe_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "ingredients": row.get("ingredients") or [],
        "steps": row.get("steps") or [],
        "prep_time_min": row.get("prep_time_min"),
        "cook_time_min": row.get("cook_time_min"),
        "servings": row.get("servings", 1),
        "categories": list(row.get("categories") or []),
        "source_url": row.get("source_url") or "",
        "rating": row.get("rating"),
        "chef_comments": row.get("chef_comments") or "",
        "notes": row.get("notes") or "",
        "checked_ingredients": list(row.get("checked_ingredients") or []),
        "checked_ingredients_at": row["checked_ingredients_at"].isoformat() if row.get("checked_ingredients_at") else None,
        "checked_steps": list(row.get("checked_steps") or []),
        "checked_steps_at": row["checked_steps_at"].isoformat() if row.get("checked_steps_at") else None,
        "last_opened_at": row["last_opened_at"].isoformat() if row.get("last_opened_at") else None,
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _cat_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "sort_order": row.get("sort_order", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _image_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "filename": row.get("filename") or "",
        "mime_type": row.get("mime_type") or "",
        "size_bytes": row.get("size_bytes", 0),
        "storage_path": row.get("storage_path") or "",
        "sort_order": row.get("sort_order", 0),
        "uploaded_by": row.get("uploaded_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# ---------------------------------------------------------------------------
BACKFILL_ENTITIES = [
    {"entity_type": "recipe", "list_fn": get_all_recipes, "context_hint": _RECIPE_HINT},
]
