> **DEPRECATED** — Moved to `apps/recipes/guide.md` (app package).
> This file is no longer loaded. Safe to delete.

# Recipes Guide

## Overview

The Recipes app manages a family recipe collection. Recipes (`re-*`) are structured entities
with ingredients, steps, categories, ratings, and images. They are NOT documents — do not
use `create_doc` for recipes.

## Available Tools

### Recipe CRUD (MCP tools)

- `create_recipe(title, created_by, ingredients, steps, ...)` — create a new recipe
- `get_recipe(recipe_id)` — get full recipe details
- `list_recipes(category?, created_by?)` — list all recipes, optionally filtered
- `search_recipes(query)` — search by title, description, or ingredients
- `update_recipe(recipe_id, title?, ingredients?, steps?, ...)` — partial update
- `delete_recipe(recipe_id)` — delete permanently

### Category CRUD (MCP tools)

- `list_recipe_categories()` — list all defined categories
- `create_recipe_category(name)` — create a new category (e.g. "Mexican", "Sauces")
- `delete_recipe_category(category_id)` — delete a category

### Visual App (local tool)

- `open_app(app_type="recipes")` — open the recipe list/browser
- `open_app(app_type="recipe", recipeId="re-abc123")` — open a specific recipe

## Creating Recipes via Chat

When a user pastes recipe text or says "create a recipe", parse it and call `create_recipe`:

```
create_recipe(
  title="Salsa",
  created_by="alice",
  description="Fresh homemade salsa",
  ingredients='[{"item":"Crushed tomatoes","quantity":"1","unit":"large can"},{"item":"Cilantro","quantity":"1","unit":"handful"}]',
  steps='["Add all ingredients to a Mason jar.","Blend with immersion blender."]',
  prep_time_min=15,
  servings=8,
  categories='["Mexican","Sauces"]'
)
```

**After creating, ALWAYS call open_app to open it:**
```
1. create_recipe(...) → returns re-abc123
2. open_app(app_type="recipe", recipeId="re-abc123")
```

### Parsing Rules

- **ingredients** — each MUST be `{item, quantity, unit}`. Parse "1/2 tsp Garlic salt" → `{"item":"Garlic salt","quantity":"1/2","unit":"tsp"}`
- **steps** — ordered array of strings, one clear instruction per step
- **categories** — infer from content (e.g. "Mexican", "Sauces", "Breakfast", "Dessert")
- **prep_time_min / cook_time_min** — estimate if not stated
- **servings** — extract or estimate
- **JSON string args** — ingredients, steps, and categories are passed as JSON strings, not native arrays

## Retrieving Recipes

When a user asks about a recipe (e.g. "what's my recipe for parmesan cheese?", "do I have a salsa recipe?",
"find my chicken tikka recipe"), **always search first** — never ask for clarification:

1. Call `search_recipes(query="parmesan")` using the key ingredient or dish name
2. If results come back, present them or open the matching recipe
3. If no results, THEN tell the user you couldn't find it and ask if they'd like to create one

**Do NOT ask the user what they titled the recipe.** Just search. The search covers title,
description, and ingredients, so partial matches work fine.

## Important Rules

1. **NEVER create a document (`d-*`) for a recipe.** Always use `create_recipe`.
2. **Always open after creating.** Call `open_app` immediately after `create_recipe`. Do NOT ask.
3. **Search first, ask later.** When a user asks about a recipe, call `search_recipes` immediately. Never ask for the title or clarification before searching.
4. **Parse aggressively.** Even messy text should be parsed into structured fields.
5. **Ingredient format matters.** Always split into item/quantity/unit. The UI depends on this for scaling.
6. **Infer categories.** If not specified, infer reasonable ones from the recipe content.

## Recipe Data Model

```
recipe {
  id: "re-{hex8}"
  title, description, ingredients, steps
  prep_time_min, cook_time_min, servings
  categories: [string]     — predefined category names
  rating: 1-5 stars        — set via UI, not chat
  chef_comments: string    — observations, proposed changes
  checked_ingredients: []  — cooking mode (UI-managed)
  source_url: string       — where the recipe came from
}
```
