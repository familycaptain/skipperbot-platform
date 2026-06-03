"""Recipes API Routes
====================
FastAPI router for recipe CRUD, categories, and image links.
Mounted at /api/apps/recipes/ by the app platform loader.
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.recipes import data as _dl

router = APIRouter()


def _actor(request: Request) -> str:
    """The authenticated actor's name. Auth is unconditional, so a verified
    principal is always present; the client-supplied value is never trusted."""
    p = current_principal(request)
    return (p["name"] if p else "").lower().strip()


# ---------------------------------------------------------------------------
# Recipe list / search
# ---------------------------------------------------------------------------

@router.get("")
async def api_list_recipes(category: str = "", q: str = ""):
    """List recipes, optionally filtered by category or search query."""
    def _fetch():
        if q.strip():
            return _dl.search_recipes(q.strip())
        if category.strip():
            return _dl.filter_by_category(category.strip())
        return _dl.get_all_recipes()
    recipes = await asyncio.to_thread(_fetch)
    return {"recipes": recipes, "count": len(recipes)}


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@router.get("/categories")
async def api_list_recipe_categories():
    cats = await asyncio.to_thread(_dl.get_all_categories_merged)
    return {"categories": cats}


class CreateCategoryRequest(BaseModel):
    name: str


@router.post("/categories")
async def api_create_recipe_category(request: CreateCategoryRequest):
    cat_id = f"cat-{uuid.uuid4().hex[:8]}"
    cat = await asyncio.to_thread(_dl.create_category, cat_id, request.name.strip())
    if not cat:
        return {"error": "Failed to create category"}, 400
    return cat


class UpdateCategoryRequest(BaseModel):
    name: str


@router.put("/categories/{cat_id}")
async def api_update_recipe_category(cat_id: str, request: UpdateCategoryRequest):
    ok = await asyncio.to_thread(_dl.update_category, cat_id, request.name.strip())
    if not ok:
        return {"error": "Category not found"}, 404
    return {"ok": True}


@router.delete("/categories/{cat_id}")
async def api_delete_recipe_category(cat_id: str):
    ok = await asyncio.to_thread(_dl.delete_category, cat_id)
    if not ok:
        return {"error": "Category not found"}, 404
    return {"ok": True}


# ---------------------------------------------------------------------------
# Single recipe CRUD
# ---------------------------------------------------------------------------

@router.get("/{recipe_id}")
async def api_get_recipe(recipe_id: str):
    def _fetch():
        recipe = _dl.get_recipe(recipe_id)
        if not recipe:
            return None
        # Auto-reset checked items if stale (>24 hours since last check).
        # Each list is checked independently. Runs BEFORE touch_recipe.
        def _is_stale(ts_str):
            if not ts_str:
                return True
            try:
                return (datetime.now(timezone.utc) - datetime.fromisoformat(ts_str)) > timedelta(hours=24)
            except (ValueError, TypeError):
                return True

        resets = {}
        if recipe.get("checked_ingredients") and _is_stale(recipe.get("checked_ingredients_at")):
            resets["checked_ingredients"] = []
        if recipe.get("checked_steps") and _is_stale(recipe.get("checked_steps_at")):
            resets["checked_steps"] = []
        if resets:
            _dl.update_recipe(recipe_id, resets)
            recipe.update(resets)
        _dl.touch_recipe(recipe_id)
        recipe["images"] = _dl.get_recipe_images(recipe_id)
        return recipe
    recipe = await asyncio.to_thread(_fetch)
    if not recipe:
        return {"error": "Recipe not found"}, 404
    return recipe


class CreateRecipeRequest(BaseModel):
    title: str
    created_by: str
    description: str = ""
    ingredients: list = []
    steps: list = []
    prep_time_min: int | None = None
    cook_time_min: int | None = None
    servings: int = 1
    categories: list = []
    source_url: str = ""
    chef_comments: str = ""
    notes: str = ""


@router.post("")
async def api_create_recipe(request: CreateRecipeRequest, http_request: Request):
    request.created_by = _actor(http_request)
    recipe_id = f"re-{uuid.uuid4().hex[:8]}"
    recipe = {
        "id": recipe_id,
        "title": request.title.strip(),
        "description": request.description.strip(),
        "ingredients": request.ingredients,
        "steps": request.steps,
        "prep_time_min": request.prep_time_min,
        "cook_time_min": request.cook_time_min,
        "servings": request.servings,
        "categories": request.categories,
        "source_url": request.source_url.strip(),
        "chef_comments": request.chef_comments.strip(),
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    await asyncio.to_thread(_dl.save_recipe, recipe)
    return _dl.get_recipe(recipe_id)


class UpdateRecipeRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    ingredients: list | None = None
    steps: list | None = None
    prep_time_min: int | None = None
    cook_time_min: int | None = None
    servings: int | None = None
    categories: list | None = None
    source_url: str | None = None
    rating: int | None = None
    chef_comments: str | None = None
    notes: str | None = None
    checked_ingredients: list | None = None
    checked_steps: list | None = None


@router.put("/{recipe_id}")
async def api_update_recipe(recipe_id: str, request: UpdateRecipeRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        return {"error": "No fields to update"}, 400
    ok = await asyncio.to_thread(_dl.update_recipe, recipe_id, updates)
    if not ok:
        return {"error": "Recipe not found"}, 404
    return await asyncio.to_thread(_dl.get_recipe, recipe_id)


@router.delete("/{recipe_id}")
async def api_delete_recipe(recipe_id: str):
    ok = await asyncio.to_thread(_dl.delete_recipe, recipe_id)
    if not ok:
        return {"error": "Recipe not found"}, 404
    return {"ok": True}


# ---------------------------------------------------------------------------
# Recipe–Image links
# ---------------------------------------------------------------------------

@router.post("/{recipe_id}/images/{image_id}/link")
async def api_link_image_to_recipe(recipe_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_image, recipe_id, image_id)
    return {"ok": True}


@router.post("/{recipe_id}/images/{image_id}/unlink")
async def api_unlink_image_from_recipe(recipe_id: str, image_id: str):
    await asyncio.to_thread(_dl.unlink_image, recipe_id, image_id)
    return {"ok": True}
