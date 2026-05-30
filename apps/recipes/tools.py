"""
Recipe Tools — Create and manage family recipes.
All recipes are stored as re-* entities with structured ingredients, steps, and categories.
"""

import json
import uuid

from config import logger
from apps.recipes import data as _dl


def create_recipe(
    title: str,
    created_by: str,
    ingredients: str = "[]",
    steps: str = "[]",
    description: str = "",
    prep_time_min: int = 0,
    cook_time_min: int = 0,
    servings: int = 1,
    categories: str = "[]",
    source_url: str = "",
    chef_comments: str = "",
    notes: str = "",
) -> str:
    """Create a new recipe with structured ingredients and steps.

    Use this when the user pastes recipe text or asks you to create a recipe.
    Parse their text into structured fields and call this tool.
    After creating, ALWAYS call open_app(app_type="recipe", context={"recipeId": "<the_id>"})
    to open the recipe on the user's desktop.

    Each ingredient must be a JSON object with "item", "quantity", and "unit" fields.
    Steps are a JSON array of strings (one per instruction step).

    Args:
        title: Recipe title (e.g. "Salsa", "Chicken Tikka Masala").
        created_by: Who is creating it (e.g. "alice").
        ingredients: JSON array of ingredient objects, each with "item", "quantity", "unit".
                     Example: '[{"item": "Crushed tomatoes", "quantity": "1", "unit": "large can"}]'
        steps: JSON array of instruction strings.
               Example: '["Blend all ingredients.", "Add water to fill jar."]'
        description: Short description of the recipe (1-2 sentences).
        prep_time_min: Prep time in minutes (0 if unknown).
        cook_time_min: Cook time in minutes (0 if unknown).
        servings: Number of servings the recipe makes.
        categories: JSON array of category names (e.g. '["Mexican", "Sauces"]').
        source_url: Source URL if the recipe came from a website.
        chef_comments: Observations or proposed changes for next time.
        notes: Additional notes.

    Returns:
        Confirmation with recipe ID. Use this ID to open_app.

    Ack: Creating recipe "{title}"...
    """
    try:
        if not title or not title.strip():
            return "Error: title is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        # Parse JSON string arguments
        try:
            ing_list = json.loads(ingredients) if isinstance(ingredients, str) else ingredients
        except (json.JSONDecodeError, TypeError):
            ing_list = []

        try:
            step_list = json.loads(steps) if isinstance(steps, str) else steps
        except (json.JSONDecodeError, TypeError):
            step_list = []

        try:
            cat_list = json.loads(categories) if isinstance(categories, str) else categories
        except (json.JSONDecodeError, TypeError):
            cat_list = []

        recipe_id = f"re-{uuid.uuid4().hex[:8]}"
        recipe = {
            "id": recipe_id,
            "title": title.strip(),
            "description": description.strip() if description else "",
            "ingredients": ing_list,
            "steps": step_list,
            "prep_time_min": prep_time_min if prep_time_min else None,
            "cook_time_min": cook_time_min if cook_time_min else None,
            "servings": servings or 1,
            "categories": cat_list,
            "source_url": source_url.strip() if source_url else "",
            "chef_comments": chef_comments.strip() if chef_comments else "",
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip(),
        }

        _dl.save_recipe(recipe)
        logger.info("RECIPE: Created '%s' (%s) by %s", title.strip(), recipe_id, created_by.strip())

        cat_display = f"\n  Categories: {', '.join(cat_list)}" if cat_list else ""
        return (
            f"Recipe created: '{title.strip()}' ({recipe_id})\n"
            f"  Ingredients: {len(ing_list)} | Steps: {len(step_list)} | Servings: {servings}"
            f"{cat_display}\n"
            f"Now call open_app(app_type=\"recipe\", recipeId=\"{recipe_id}\") to open it."
        )

    except Exception as e:
        return f"Error in create_recipe: {str(e)}"


def get_recipe(recipe_id: str) -> str:
    """Get a recipe's full details including ingredients, steps, and metadata.

    Args:
        recipe_id: The recipe ID (e.g. "re-abc12345").

    Returns:
        Formatted recipe details.

    Ack: Loading recipe...
    """
    try:
        if not recipe_id or not recipe_id.strip():
            return "Error: recipe_id is required."

        recipe = _dl.get_recipe(recipe_id.strip())
        if not recipe:
            return f"Error: Recipe '{recipe_id}' not found."

        return _format_recipe(recipe)

    except Exception as e:
        return f"Error in get_recipe: {str(e)}"


def list_recipes(category: str = "", created_by: str = "") -> str:
    """List all recipes, optionally filtered by category or creator.

    Args:
        category: Filter by category name (e.g. "Mexican"). Empty = all recipes.
        created_by: Filter by creator (e.g. "alice"). Empty = all users.

    Returns:
        Formatted list of recipes with basic metadata.

    Ack: Listing recipes...
    """
    try:
        if category and category.strip():
            recipes = _dl.filter_by_category(category.strip())
        else:
            recipes = _dl.get_all_recipes()

        if created_by and created_by.strip():
            recipes = [r for r in recipes if r.get("created_by") == created_by.strip()]

        if not recipes:
            if category:
                return f"No recipes found in category '{category}'."
            return "No recipes found."

        lines = [f"Found {len(recipes)} recipe(s):\n"]
        for r in recipes:
            rating = f" {'★' * r['rating']}{'☆' * (5 - r['rating'])}" if r.get("rating") else ""
            cats = f" [{', '.join(r['categories'])}]" if r.get("categories") else ""
            lines.append(f"- {r['title']} ({r['id']}){rating}{cats}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_recipes: {str(e)}"


def search_recipes(query: str) -> str:
    """Search recipes by title, description, or ingredients.

    Args:
        query: Search terms (e.g. "chicken", "salsa", "garlic").

    Returns:
        Matching recipes with basic metadata.

    Ack: Searching recipes for "{query}"...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."

        recipes = _dl.search_recipes(query.strip())
        if not recipes:
            return f"No recipes match '{query}'."

        lines = [f"Found {len(recipes)} recipe(s) matching '{query}':\n"]
        for r in recipes:
            cats = f" [{', '.join(r['categories'])}]" if r.get("categories") else ""
            lines.append(f"- {r['title']} ({r['id']}){cats}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in search_recipes: {str(e)}"


def update_recipe(
    recipe_id: str,
    title: str = "",
    description: str = "",
    ingredients: str = "",
    steps: str = "",
    prep_time_min: int = -1,
    cook_time_min: int = -1,
    servings: int = -1,
    categories: str = "",
    source_url: str = "",
    chef_comments: str = "",
    notes: str = "",
    rating: int = -1,
) -> str:
    """Update an existing recipe. Only provided fields are changed.

    Pass -1 for integer fields to leave them unchanged. Pass empty string
    for text fields to leave them unchanged.

    Args:
        recipe_id: The recipe to update (e.g. "re-abc12345").
        title: New title (empty = keep current).
        description: New description (empty = keep current).
        ingredients: New ingredients as JSON array (empty = keep current).
        steps: New steps as JSON array (empty = keep current).
        prep_time_min: New prep time (-1 = keep current, 0 = clear).
        cook_time_min: New cook time (-1 = keep current, 0 = clear).
        servings: New servings (-1 = keep current).
        categories: New categories as JSON array (empty = keep current).
        source_url: New source URL (empty = keep current).
        chef_comments: New chef comments (empty = keep current).
        notes: New notes (empty = keep current).
        rating: New rating 1-5 (-1 = keep current, 0 = clear).

    Returns:
        Confirmation of update.

    Ack: Updating recipe {recipe_id}...
    """
    try:
        if not recipe_id or not recipe_id.strip():
            return "Error: recipe_id is required."

        updates = {}
        if title:
            updates["title"] = title.strip()
        if description:
            updates["description"] = description.strip()
        if ingredients:
            try:
                updates["ingredients"] = json.loads(ingredients) if isinstance(ingredients, str) else ingredients
            except json.JSONDecodeError:
                return "Error: ingredients must be valid JSON."
        if steps:
            try:
                updates["steps"] = json.loads(steps) if isinstance(steps, str) else steps
            except json.JSONDecodeError:
                return "Error: steps must be valid JSON."
        if prep_time_min >= 0:
            updates["prep_time_min"] = prep_time_min if prep_time_min > 0 else None
        if cook_time_min >= 0:
            updates["cook_time_min"] = cook_time_min if cook_time_min > 0 else None
        if servings >= 0:
            updates["servings"] = servings
        if categories:
            try:
                updates["categories"] = json.loads(categories) if isinstance(categories, str) else categories
            except json.JSONDecodeError:
                return "Error: categories must be valid JSON."
        if source_url:
            updates["source_url"] = source_url.strip()
        if chef_comments:
            updates["chef_comments"] = chef_comments.strip()
        if notes:
            updates["notes"] = notes.strip()
        if rating >= 0:
            updates["rating"] = rating if rating > 0 else None

        if not updates:
            return "No fields to update."

        success = _dl.update_recipe(recipe_id.strip(), updates)
        if success:
            fields = ", ".join(updates.keys())
            return f"Recipe {recipe_id} updated. Changed: {fields}"
        return f"Error: Recipe '{recipe_id}' not found."

    except Exception as e:
        return f"Error in update_recipe: {str(e)}"


def delete_recipe(recipe_id: str) -> str:
    """Delete a recipe permanently.

    Args:
        recipe_id: The recipe to delete (e.g. "re-abc12345").

    Returns:
        Confirmation or error.

    Ack: Deleting recipe {recipe_id}...
    """
    try:
        if not recipe_id or not recipe_id.strip():
            return "Error: recipe_id is required."

        success = _dl.delete_recipe(recipe_id.strip())
        if success:
            return f"Recipe '{recipe_id}' deleted."
        return f"Error: Recipe '{recipe_id}' not found."

    except Exception as e:
        return f"Error in delete_recipe: {str(e)}"


def list_recipe_categories() -> str:
    """List all available recipe categories.

    Returns:
        Formatted list of categories.

    Ack: Listing recipe categories...
    """
    try:
        cats = _dl.get_all_categories()
        if not cats:
            return "No categories defined yet."

        lines = [f"Recipe categories ({len(cats)}):\n"]
        for c in cats:
            lines.append(f"- {c['name']} ({c['id']})")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_recipe_categories: {str(e)}"


def create_recipe_category(name: str) -> str:
    """Create a new recipe category.

    Args:
        name: Category name (e.g. "Mexican", "Sauces", "Dessert").

    Returns:
        Confirmation with category ID.

    Ack: Creating category "{name}"...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."

        cat_id = f"cat-{uuid.uuid4().hex[:8]}"
        cat = _dl.create_category(cat_id, name.strip())
        if cat:
            return f"Category created: '{cat['name']}' ({cat['id']})"
        return "Error: Category creation failed (name may already exist)."

    except Exception as e:
        return f"Error in create_recipe_category: {str(e)}"


def update_recipe_category(category_id: str, name: str) -> str:
    """Rename a recipe category.

    Args:
        category_id: The category to rename (e.g. "cat-abc12345").
        name: New category name.

    Returns:
        Confirmation or error.

    Ack: Renaming category {category_id}...
    """
    try:
        if not category_id or not category_id.strip():
            return "Error: category_id is required."
        if not name or not name.strip():
            return "Error: name is required."

        success = _dl.update_category(category_id.strip(), name.strip())
        if success:
            return f"Category '{category_id}' renamed to '{name.strip()}'."
        return f"Error: Category '{category_id}' not found."

    except Exception as e:
        return f"Error in update_recipe_category: {str(e)}"


def delete_recipe_category(category_id: str) -> str:
    """Delete a recipe category.

    Args:
        category_id: The category to delete (e.g. "cat-abc12345").

    Returns:
        Confirmation or error.

    Ack: Deleting category {category_id}...
    """
    try:
        if not category_id or not category_id.strip():
            return "Error: category_id is required."

        success = _dl.delete_category(category_id.strip())
        if success:
            return f"Category '{category_id}' deleted."
        return f"Error: Category '{category_id}' not found."

    except Exception as e:
        return f"Error in delete_recipe_category: {str(e)}"


def print_recipe(
    recipe_id: str,
    requested_by: str,
    copies: str = "1",
) -> str:
    """Print a recipe to the default physical printer.

    The recipe is rendered as a nicely formatted page with title,
    ingredients list, numbered instructions, and meta info —
    ready to pin on the fridge or take to the kitchen.

    Args:
        recipe_id: The recipe ID to print (e.g. "re-abc12345").
        requested_by: Who is requesting the print (e.g. "alice").
        copies: Number of copies to print, 1-10. Defaults to "1".

    Returns:
        Confirmation with job ID.

    Ack: Sending recipe to printer...
    """
    try:
        if not recipe_id or not recipe_id.strip():
            return "Error: recipe_id is required."
        if not requested_by or not requested_by.strip():
            return "Error: requested_by is required."

        recipe_id = recipe_id.strip()
        if not recipe_id.startswith("re-"):
            return f"Error: '{recipe_id}' doesn't look like a recipe ID (expected re-*)."

        try:
            n = int(copies)
        except (ValueError, TypeError):
            n = 1

        from apps.jobs.store import create_recipe_print_job as _create_recipe_print_job
        job = _create_recipe_print_job(
            recipe_id=recipe_id,
            requested_by=requested_by.strip(),
            copies=n,
        )

        copies_msg = f"{n} {'copy' if n == 1 else 'copies'}"
        return (
            f"Print job queued ({job['id']})\n"
            f"  Recipe: {recipe_id}\n"
            f"  Copies: {copies_msg}\n"
            f"  Status: queued (will start within ~30 seconds)\n"
            f"I'll notify you when it's been sent to the printer."
        )

    except Exception as e:
        return f"Error in print_recipe: {str(e)}"


# ---------------------------------------------------------------------------
# Helpers (private — not registered as MCP tools)
# ---------------------------------------------------------------------------

def _format_recipe(r: dict) -> str:
    """Format a recipe for text output."""
    rating = f"Rating: {'★' * r['rating']}{'☆' * (5 - r['rating'])} ({r['rating']}/5)\n" if r.get("rating") else ""
    cats = f"Categories: {', '.join(r['categories'])}\n" if r.get("categories") else ""
    desc = f"{r['description']}\n" if r.get("description") else ""

    times = []
    if r.get("prep_time_min"):
        times.append(f"Prep: {r['prep_time_min']}m")
    if r.get("cook_time_min"):
        times.append(f"Cook: {r['cook_time_min']}m")
    time_line = f"{' | '.join(times)} | " if times else ""

    ingredients = ""
    if r.get("ingredients"):
        ing_lines = []
        for ing in r["ingredients"]:
            qty = f"{ing.get('quantity', '')} " if ing.get("quantity") else ""
            unit = f"{ing.get('unit', '')} " if ing.get("unit") else ""
            ing_lines.append(f"  - {qty}{unit}{ing.get('item', '')}")
        ingredients = "Ingredients:\n" + "\n".join(ing_lines) + "\n"

    steps_text = ""
    if r.get("steps"):
        step_lines = [f"  {i+1}. {s}" for i, s in enumerate(r["steps"])]
        steps_text = "Steps:\n" + "\n".join(step_lines) + "\n"

    chef = f"Chef Comments: {r['chef_comments']}\n" if r.get("chef_comments") else ""
    source = f"Source: {r['source_url']}\n" if r.get("source_url") else ""

    return (
        f"# {r['title']} ({r['id']})\n"
        f"{desc}{rating}{cats}"
        f"{time_line}Servings: {r.get('servings', 1)} | By: {r.get('created_by', '?')}\n"
        f"---\n"
        f"{ingredients}{steps_text}{chef}{source}"
    ).strip()
