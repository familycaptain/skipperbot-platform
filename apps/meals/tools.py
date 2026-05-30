"""
Meals App Tools — Meal idea generator and library management.
Meals are built from reusable components (proteins, starches, sauces, etc.)
and classified by effort and tags (cuisine is a tag, e.g. 'american', 'mexican').
"""

import json
import random
import re
import uuid
from difflib import SequenceMatcher

from config import logger
from apps.meals import data as _dl


# ---------------------------------------------------------------------------
# Discover / Filter
# ---------------------------------------------------------------------------

def find_meals(filters: str = "[]") -> str:
    """Find meals matching include/exclude filter criteria.

    Use this to answer "what should we eat?" style queries. Combine include
    and exclude filters to narrow down the meal library.

    Args:
        filters: JSON array of filter objects. Each object has:
            - type: "tag" | "effort" | "component" (use "tag" for cuisine too)
            - mode: "include" | "exclude"
            - value: the value to filter on

            effort values: "low", "medium", "high"
            Examples:
            '[{"type":"tag","mode":"exclude","value":"mexican"},
              {"type":"effort","mode":"include","value":"low"}]'
            '[{"type":"component","mode":"include","value":"potatoes"}]'
            '[{"type":"tag","mode":"include","value":"kid-friendly"}]'

    Returns:
        Formatted list of matching meals with effort and tags.

    Ack: Searching meals...
    """
    try:
        filter_list = json.loads(filters) if isinstance(filters, str) else filters
    except (json.JSONDecodeError, TypeError):
        return "Error: filters must be a valid JSON array."

    meals = _dl.discover_meals(filter_list)
    if not meals:
        return "No meals match those filters. Try relaxing the criteria."

    lines = [f"Found {len(meals)} meal(s):\n"]
    for m in meals:
        effort_label = {"low": "⚡ Low", "medium": "🔥 Medium", "high": "⏳ High"}.get(m["effort"], m["effort"])
        tags_str = ", ".join(m["tags"]) if m["tags"] else ""
        tags_display = f" | {tags_str}" if tags_str else ""
        rating_str = f" | {'★' * m['rating']}" if m.get("rating") else ""
        lines.append(f"• **{m['name']}** ({m['id']}) — {effort_label}{tags_display}{rating_str}")

    return "\n".join(lines)


def list_all_meals(effort: str = "", q: str = "", tag: str = "") -> str:
    """List all meals in the library, optionally filtered by tag, effort, or search.

    Args:
        effort: Filter by effort level: "low", "medium", or "high". Leave blank for all.
        q: Search term to match against meal names.
        tag: Filter by a specific tag (e.g. "mexican", "kid-friendly", "dinner").

    Returns:
        Formatted meal list.

    Ack: Fetching meals...
    """
    meals = _dl.list_meals(effort=effort, q=q, tag=tag)
    if not meals:
        return "No meals found."

    lines = [f"{len(meals)} meal(s):\n"]
    for m in meals:
        effort_label = {"low": "⚡", "medium": "🔥", "high": "⏳"}.get(m["effort"], "")
        tags_str = f" [{', '.join(m['tags'][:3])}]" if m.get("tags") else ""
        lines.append(f"• **{m['name']}** ({m['id']}){tags_str} {effort_label}")
    return "\n".join(lines)


def random_meals(count: int = 3, tag: str = "", effort: str = "", filters: str = "[]") -> str:
    """Pick random meal ideas from the library, optionally filtered by tag or effort.

    Use this when the user asks for random meal options, random dinner ideas,
    or a specific number of ideas like "3 random #snack options".

    Args:
        count: Number of random meal options to return. Defaults to 3.
        tag: Optional tag filter, such as "snack", "#snack", "dinner", or "italian".
        effort: Optional effort filter: "low", "medium", or "high".
        filters: Optional JSON array of additional find_meals-style filters.

    Returns:
        A random list of matching meals with tags and effort.

    Ack: Picking meal ideas...
    """
    try:
        requested_count = int(count)
    except (TypeError, ValueError):
        requested_count = 3
    requested_count = max(1, min(requested_count, 10))

    try:
        filter_list = json.loads(filters) if isinstance(filters, str) else (filters or [])
    except (json.JSONDecodeError, TypeError):
        return "Error: filters must be a valid JSON array."
    if not isinstance(filter_list, list):
        return "Error: filters must be a JSON array."

    if tag and tag.strip():
        filter_list.append({"type": "tag", "mode": "include", "value": tag.strip()})
    if effort and effort.strip():
        filter_list.append({"type": "effort", "mode": "include", "value": effort.strip()})

    meals = _dl.discover_meals(filter_list)
    if not meals:
        return "No meals match those filters. Try relaxing the criteria."

    picks = random.sample(meals, min(requested_count, len(meals)))
    lines = [f"{len(picks)} random meal option(s) from {len(meals)} match(es):\n"]
    for m in picks:
        effort_label = {"low": "âš¡", "medium": "ðŸ”¥", "high": "â³"}.get(m["effort"], "")
        tags_str = f" [{', '.join(m['tags'][:4])}]" if m.get("tags") else ""
        rating_str = f" | {'â˜…' * m['rating']}" if m.get("rating") else ""
        lines.append(f"â€¢ **{m['name']}** ({m['id']}){tags_str} {effort_label}{rating_str}")
    return "\n".join(lines)


def _normalize_meal_name(value: str) -> tuple[list[str], str]:
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    return tokens, " ".join(tokens)


def _meal_name_similarity(query: str, candidate: str) -> float:
    q_tokens, q_norm = _normalize_meal_name(query)
    c_tokens, c_norm = _normalize_meal_name(candidate)
    if not q_norm or not c_norm:
        return 0.0
    if q_norm == c_norm:
        return 1.0

    seq_score = SequenceMatcher(None, q_norm, c_norm).ratio()
    q_set = set(q_tokens)
    c_set = set(c_tokens)
    overlap = len(q_set & c_set)
    if not overlap:
        return seq_score

    overlap_score = overlap / max(len(q_set), len(c_set))
    subset_match = q_set <= c_set or c_set <= q_set
    score = max(seq_score, (seq_score * 0.7) + (overlap_score * 0.3))
    if subset_match:
        score = max(score, 0.9)
    return min(score, 1.0)


def _candidate_entry(meal: dict, source: str, score: float = 0.0) -> dict:
    return {"meal": meal, "sources": [source], "score": score}


def _merge_candidate(candidates: dict[str, dict], meal: dict, source: str, score: float = 0.0) -> None:
    meal_id = meal["id"]
    entry = candidates.get(meal_id)
    if not entry:
        candidates[meal_id] = _candidate_entry(meal, source, score)
        return
    if source not in entry["sources"]:
        entry["sources"].append(source)
    entry["score"] = max(entry["score"], score)


def _get_fuzzy_name_candidates(main_name: str, limit: int = 8, threshold: float = 0.45) -> list[dict]:
    meals = _dl.list_meals()
    scored = []
    for meal in meals:
        score = _meal_name_similarity(main_name, meal.get("name", ""))
        if score >= threshold:
            scored.append((score, meal))

    scored.sort(key=lambda item: (-item[0], len(item[1].get("name", "")), item[1].get("name", "")))
    return [
        _candidate_entry(meal, f"fuzzy name ({score:.2f})", score)
        for score, meal in scored[:limit]
    ]


def _build_meal_match_candidates(main_name: str, main_component_id: str) -> list[dict]:
    candidates: dict[str, dict] = {}

    exact = _dl.find_meal_by_name(main_name)
    if exact:
        _merge_candidate(candidates, exact, "exact name", 1.0)

    for entry in _get_fuzzy_name_candidates(main_name):
        meal = entry["meal"]
        _merge_candidate(candidates, meal, entry["sources"][0], entry["score"])

    for meal in _dl.get_meals_with_main(main_component_id):
        _merge_candidate(candidates, meal, "main component", 0.95)

    return sorted(
        candidates.values(),
        key=lambda item: (-item["score"], len(item["meal"].get("name", "")), item["meal"].get("name", "")),
    )


# ---------------------------------------------------------------------------
# Meal CRUD
# ---------------------------------------------------------------------------

def get_meal(meal_id: str) -> str:
    """Get full details for a meal including its components.

    Args:
        meal_id: The ml-* meal ID.

    Returns:
        Formatted meal detail with components, tags, and effort.
    """
    meal = _dl.get_meal(meal_id)
    if not meal:
        return f"Meal {meal_id} not found."

    lines = [f"**{meal['name']}** ({meal_id})"]
    lines.append(f"Effort: {meal['effort']}")
    if meal.get("prep_time_min") or meal.get("cook_time_min"):
        t = []
        if meal.get("prep_time_min"):
            t.append(f"prep {meal['prep_time_min']}min")
        if meal.get("cook_time_min"):
            t.append(f"cook {meal['cook_time_min']}min")
        lines.append("Time: " + ", ".join(t))
    if meal.get("tags"):
        lines.append("Tags: " + ", ".join(meal["tags"]))
    if meal.get("rating"):
        lines.append("Rating: " + "★" * meal["rating"])
    if meal.get("description"):
        lines.append(f"Description: {meal['description']}")
    if meal.get("notes"):
        lines.append(f"Notes: {meal['notes']}")

    components = meal.get("components", [])
    if components:
        lines.append("\nComponents:")
        role_order = {"main": 0, "side": 1, "sauce": 2, "garnish": 3, "other": 4}
        for c in sorted(components, key=lambda x: role_order.get(x["role"], 5)):
            role_label = c["role"].capitalize()
            recipe_note = f" (recipe: {c['component_recipe_id']})" if c.get("component_recipe_id") else ""
            notes_str = f" — {c['notes']}" if c.get("notes") else ""
            lines.append(f"  [{role_label}] {c['component_name']}{recipe_note}{notes_str}")

    return "\n".join(lines)


def add_meal(
    name: str,
    created_by: str,
    effort: str = "medium",
    tags: str = "[]",
    description: str = "",
    notes: str = "",
    rating: int = 0,
    components: str = "[]",
) -> str:
    """Add a meal idea to the library WITHOUT creating a meal log entry.

    Use this when the user says things like "here is a meal idea",
    "a meal idea for dinner is ...", "save this meal", or
    "add this to my meal ideas" — i.e. they are NOT saying they ate it right now.
    If "meal idea" appears, treat meal words like dinner/lunch/breakfast/snack
    as tagging hints for the reusable meal, not evidence that it was eaten.
    If the user DID eat the meal, use log_meal() instead (it adds to the library automatically).

    Looks up the meal by name first:
    - If it already exists: expands it with any new sides and merges tags/effort/notes.
    - If not: creates the meal idea, then links all components.

    Args:
        name: Meal name (e.g., "Chicken Tacos", "BLT Sandwich").
        created_by: Who is creating it (e.g., "user").
        effort: Effort level: "low", "medium", or "high".
        tags: JSON array of tag strings. Must include cuisine + occasion(s) + descriptor(s).
              e.g. '["dinner","lunch","italian","pasta","comfort food"]'
        description: Brief description of the meal.
        notes: Any notes about the meal.
        rating: Star rating 1-5, or 0 for unrated.
        components: Optional JSON array of component objects (same format as log_meal).
                    Each has name, role ("main"/"side"), optional type.
                    e.g. '[{"name":"Cappuccino","role":"main","type":"other"}]'

    Returns:
        Confirmation with the meal ID and what was created or expanded.

    Ack: Saving meal idea "{name}"...
    """
    if not name or not name.strip():
        return "Error: name is required."
    if not created_by or not created_by.strip():
        return "Error: created_by is required."
    if effort not in ("low", "medium", "high"):
        effort = "medium"

    try:
        tag_list = json.loads(tags) if isinstance(tags, str) else (tags or [])
    except (json.JSONDecodeError, TypeError):
        tag_list = []

    if not tag_list:
        return "Error: at least one tag is required. Include a cuisine tag (e.g. 'american', 'italian') plus any descriptors."

    try:
        component_list = json.loads(components) if isinstance(components, str) else (components or [])
    except (json.JSONDecodeError, TypeError):
        component_list = []

    actions = []

    # Look up existing meal by name
    existing = _dl.find_meal_by_name(name.strip())

    if existing:
        meal_id = existing["id"]
        actions.append(f"Found existing meal: **{existing['name']}** ({meal_id})")
        # Merge tags
        merged_tags = list({*existing.get("tags", []), *tag_list})
        update_fields = {"tags": merged_tags}
        if effort and effort != existing.get("effort"):
            update_fields["effort"] = effort
        if description and description.strip() and not existing.get("description"):
            update_fields["description"] = description.strip()
        if notes and notes.strip():
            update_fields["notes"] = notes.strip()
        if rating and 1 <= rating <= 5:
            update_fields["rating"] = rating
        _dl.update_meal(meal_id, by=created_by, **update_fields)
        meal = _dl.get_meal(meal_id)
    else:
        meal_id = f"ml-{uuid.uuid4().hex[:8]}"
        meal = _dl.create_meal(
            meal_id=meal_id,
            name=name.strip(),
            created_by=created_by.strip(),
            effort=effort,
            description=description.strip() if description else "",
            tags=tag_list,
            notes=notes.strip() if notes else "",
            rating=rating if rating and 1 <= rating <= 5 else None,
        )
        if not meal:
            return "Error: could not create meal."
        actions.append(f"Created new meal: **{meal['name']}** ({meal_id})")

    # Find/create and link components
    for spec in component_list:
        comp = _dl.find_component_by_name(spec["name"])
        if not comp:
            comp_id = f"mc-{uuid.uuid4().hex[:8]}"
            comp = _dl.create_component(
                component_id=comp_id,
                name=spec["name"].strip(),
                comp_type=spec.get("type", "other"),
                by=created_by,
            )
            actions.append(f"Created component: **{comp['name']}** ({comp_id})")
        else:
            actions.append(f"Found component: **{comp['name']}** ({comp['id']})")
        added = _dl.link_component_to_meal(meal_id, comp["id"], role=spec.get("role", "side"))
        if added:
            actions.append(f"  → Linked to meal as {spec.get('role','side')}")

    logger.info("MEALS: add_meal '%s' (%s) by %s", name.strip(), meal_id, created_by.strip())
    lines = [f"✅ Meal idea saved: **{meal['name']}** ({meal_id})"]
    lines.append("\nLibrary updates:")
    for a in actions:
        lines.append(f"  • {a}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def list_components(q: str = "", type_filter: str = "") -> str:
    """List meal components (the reusable building blocks).

    Args:
        q: Search term to match against component names.
        type_filter: Filter by type: protein, starch, vegetable, sauce, grain, bread, dairy, fruit, other.

    Returns:
        Formatted component list.
    """
    components = _dl.list_components(q=q, type_filter=type_filter)
    if not components:
        return "No components found."

    lines = [f"{len(components)} component(s):\n"]
    for c in components:
        recipe_note = f" (recipe: {c['recipe_id']})" if c.get("recipe_id") else ""
        tags_str = f" [{', '.join(c['tags'])}]" if c.get("tags") else ""
        lines.append(f"• **{c['name']}** ({c['type']}){recipe_note}{tags_str}")
    return "\n".join(lines)


def add_component(
    name: str,
    comp_type: str = "other",
    description: str = "",
    tags: str = "[]",
    recipe_id: str = "",
    by: str = "user",
) -> str:
    """Add a new reusable meal component to the library.

    Components are the building blocks of meals (e.g., "Mashed Potatoes",
    "Grilled Chicken Breast", "Salsa Verde"). Once created they can be
    assigned to any number of meals.

    Args:
        name: Component name (e.g., "Mashed Potatoes", "Grilled Chicken").
        comp_type: Type: protein | starch | vegetable | sauce | grain | bread | dairy | fruit | other
        description: Brief description.
        tags: JSON array of tag strings (e.g., '["vegetarian", "spicy"]').
        recipe_id: Optional re-* recipe ID linking to a recipe in the Recipes app.

    Returns:
        Confirmation with the new component ID.

    Ack: Adding component "{name}"...
    """
    if not name or not name.strip():
        return "Error: name is required."

    valid_types = {"protein", "starch", "vegetable", "sauce", "grain", "bread", "dairy", "fruit", "other"}
    if comp_type not in valid_types:
        comp_type = "other"

    try:
        tag_list = json.loads(tags) if isinstance(tags, str) else tags
    except (json.JSONDecodeError, TypeError):
        tag_list = []

    comp_id = f"mc-{uuid.uuid4().hex[:8]}"
    comp = _dl.create_component(
        component_id=comp_id,
        name=name.strip(),
        comp_type=comp_type,
        description=description.strip() if description else "",
        tags=tag_list,
        recipe_id=recipe_id.strip() if recipe_id else None,
        by=by,
    )
    if not comp:
        return "Error: could not create component."

    logger.info("MEALS: Created component '%s' (%s)", name.strip(), comp_id)
    return f"Added component **{comp['name']}** ({comp_id}) — type: {comp['type']}."


def update_meal(
    meal_id: str,
    by: str = "user",
    name: str = "",
    effort: str = "",
    tags: str = "",
    description: str = "",
    notes: str = "",
    rating: int = 0,
) -> str:
    """Update meal metadata — name, effort, tags, description, notes, or rating.

    Only fields you provide are updated; omit anything you don't want to change.
    To update cuisine, update the tags array to include/remove the cuisine tag.

    Args:
        meal_id: The ml-* meal ID to update.
        by: Who is making the change (default "user").
        name: New meal name (leave blank to keep current).
        effort: Effort level: "low", "medium", or "high".
        tags: JSON array of tags to SET (replaces existing tags).
              e.g. '["kid-friendly", "weeknight", "grilled"]'
        description: Brief description of the meal.
        notes: Any notes (tips, variations, etc.).
        rating: Star rating 1-5 (0 = no change).

    Returns:
        Confirmation of what was updated.

    Ack: Updating meal...
    """
    fields = {}
    if name.strip():        fields["name"] = name.strip()
    if effort in ("low", "medium", "high"): fields["effort"] = effort
    if rating and 1 <= rating <= 5:          fields["rating"] = rating
    if description.strip(): fields["description"] = description.strip()
    if notes.strip():       fields["notes"] = notes.strip()
    if tags.strip():
        try:
            fields["tags"] = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            return "Error: tags must be a valid JSON array."

    if not fields:
        return "Nothing to update — provide at least one field to change."

    meal = _dl.update_meal(meal_id, by=by, **fields)
    if not meal:
        return f"Meal {meal_id} not found."

    changed = ", ".join(fields.keys())
    return f"Updated **{meal['name']}** ({meal_id}): {changed}."


def rate_meal(meal_id: str, rating: int, by: str = "user") -> str:
    """Set a star rating on a meal (1-5 stars).

    Quick shortcut for when the user says "that was great, 5 stars" or similar.
    Call this right after logging a meal if the user expresses satisfaction.

    Args:
        meal_id: The ml-* meal ID to rate.
        rating: Star rating 1-5 (1=poor, 3=good, 5=excellent).
        by: Who is rating (default "user").

    Returns:
        Confirmation with the meal name and new rating.

    Ack: Saving rating...
    """
    if not (1 <= rating <= 5):
        return "Error: rating must be between 1 and 5."
    meal = _dl.update_meal(meal_id, by=by, rating=rating)
    if not meal:
        return f"Meal {meal_id} not found."
    stars = "★" * rating + "☆" * (5 - rating)
    return f"Rated **{meal['name']}** {stars} ({rating}/5)."


def check_today_meals() -> str:
    """Check what meals have been logged today (all types).

    Use this when the user asks what they've eaten today, or before asking
    the dinner question to see if it's already been logged.

    Returns:
        Summary of today's logged meals by type (breakfast, lunch, dinner, snack).

    Ack: Checking today's meals...
    """
    from datetime import date
    today = date.today().isoformat()
    all_types = ("breakfast", "lunch", "dinner", "snack")
    results = []
    for mt in all_types:
        entry = _dl.get_meal_log_for_date(today, mt)
        if entry:
            results.append((mt, entry))

    if not results:
        return f"Nothing logged yet for today ({today})."

    lines = [f"Today's meals ({today}):\n"]
    for mt, entry in results:
        meal_ref = f" → {entry['meal_name']}" if entry.get("meal_name") else ""
        lines.append(f"• **{mt.capitalize()}**: {entry['description']}{meal_ref}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM Meal Matching
# ---------------------------------------------------------------------------

_MEAL_MATCH_SYSTEM = """\
You are a meal library matching assistant. When a user logs a meal, your job is to decide \
whether it matches an existing meal in the library or should be created as a new entry.

Rules:
- Match on the FULL meal identity: main dish + cuisine/style + typical sides together. \
  The combination must be essentially the same meal, not just a shared ingredient.
- Sides and cuisine tags are CONTEXT CLUES for the style of the meal — \
  do not ignore them. Two dishes with the same main component but different \
  cuisines or side profiles are DIFFERENT meals and must NOT be merged. \
  Examples that are NOT matches:
    * Rice (main) + cucumbers + mint  ≠  Rice (main) + refried beans + cheese
    * Chicken (main) + Asian vegetables  ≠  Chicken (main) + taco toppings
    * Pork (main) + fried rice + soy sauce  ≠  Pork (main) + potatoes + gravy
- Match if the meal is essentially the same preparation with minor variation \
  (e.g. a side was skipped tonight, or a common garnish was added).
- Use semantic understanding: "curry and rice" matches "Curry and Rice", \
  "chicken taco" matches "Chicken Tacos".
- Candidate meals are prefiltered by fuzzy meal-name search and/or main-component \
  search. Treat exact or close name matches as strong signals, but still compare \
  the full meal context before deciding.
- If a library meal's name and cuisine/tags clearly align with what was logged, \
  that is a strong match signal.
- When in doubt, return NEW rather than merge two different dishes.

Respond ONLY with JSON (no markdown, no explanation outside the JSON):
{"match": "<meal_id>", "reason": "<one sentence>"}
or
{"match": "NEW", "reason": "<one sentence>"}
"""


def _match_meal_with_llm(main_name: str, side_names: list[str], candidates: list[dict] | None = None) -> dict | None:
    """Use the LLM to find the best matching meal from the library.

    Fetches candidate meals, asks the LLM which one best matches the
    described main dish, and returns the matched meal dict.
    Returns None if the LLM decides this is a new meal (no match found).
    """
    from config import openai_client, DUMB_MODEL

    if candidates is None:
        candidates = [{"meal": m, "sources": ["component library"], "score": 0.0}
                      for m in _dl.get_meals_with_components(limit=150)]
    if not candidates:
        return None

    cand_lines = []
    for c in candidates:
        m = c["meal"]
        comp_parts = [comp["name"] for comp in (m.get("components") or [])]
        comp_str = ", ".join(comp_parts) if comp_parts else "no components listed"
        tags = m.get("tags") or []
        tag_str = ", ".join(tags) if tags else "no tags"
        source_str = ", ".join(c.get("sources", []))
        cand_lines.append(
            f"  - ID: {m['id']} | Name: {m['name']} | Match sources: {source_str} | Cuisine/Tags: {tag_str} | Components: {comp_str}"
        )

    side_str = ", ".join(side_names) if side_names else "none"
    user_prompt = (
        f"User just logged eating:\n"
        f"  Main dish: {main_name}\n"
        f"  Sides: {side_str}\n\n"
        f"Potential matching meals ({len(candidates)} total) from fuzzy name and/or component search:\n"
        + "\n".join(cand_lines)
    )

    try:
        response = openai_client.chat.completions.create(
            model=DUMB_MODEL,
            messages=[
                {"role": "system", "content": _MEAL_MATCH_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=256,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        meal_id = result.get("match", "NEW")
        reason = result.get("reason", "")
        logger.info("MEALS: LLM match for '%s' → %s (%s)", main_name, meal_id, reason)
        if meal_id == "NEW":
            return None
        meal = _dl.get_meal(meal_id)
        return meal if meal else None
    except Exception as exc:
        logger.warning("MEALS: LLM meal match failed for '%s': %s", main_name, exc)
        return None


# ---------------------------------------------------------------------------
# Meal Log
# ---------------------------------------------------------------------------

def log_meal(
    components: str,
    meal_type: str = "dinner",
    effort: str = "",
    tags: str = "[]",
    date: str = "",
    logged_by: str = "user",
    notes: str = "",
) -> str:
    """Record what was actually eaten (a meal log event) and grow the meal library as a side effect.

    TWO SEPARATE CONCEPTS:
    - Meal log entry = the EVENT (what was eaten, when, what meal type). Stored in meal_log table.
    - Meal idea = the ENTITY (reusable dish in the library). Stored in meals table.
    This tool creates BOTH: it records the log event, and finds/creates the meal idea automatically.
    Use add_meal() instead if you only want to add a meal idea without logging that it was eaten.

    Use log_meal() whenever the user clearly mentions what they ate — the 9pm dinner prompt,
    mentioning lunch they had, a snack they just ate, etc.
    Do NOT use this when the user is describing a "meal idea" or a meal to save for later.

    ALWAYS infer and pass effort and tags. Do not leave them blank
    for new meals — the library is only useful if it's well-tagged.

    Tags MUST include (all lowercase):
    - The occasion (same as meal_type: "dinner", "lunch", "breakfast", "snack")
    - Cuisine as a lowercase tag ("american", "italian", "mexican", "asian", etc.)
    - Any applicable descriptors ("kid-friendly", "quick", "comfort food",
      "grilled", "baked", "vegetarian", "sweet", "savory", etc.)

    Examples:
    - Chocolate muffin (snack) → effort="low",
      tags='["snack","sweet","bakery","american"]'
    - Grilled chicken + mashed potatoes (dinner) → effort="medium",
      tags='["dinner","american","grilled","weeknight"]'
    - Tacos (dinner) → effort="medium",
      tags='["dinner","mexican","kid-friendly"]'

    Args:
        components: JSON array of component objects. Each has:
            - name: component name (required, e.g. "Grilled Chicken")
            - role: "main" or "side" — exactly one must be "main"
            - type: component type hint if creating new
                    (protein/starch/vegetable/sauce/grain/bread/dairy/fruit/other)
            Example:
            '[{"name":"Grilled Chicken","role":"main","type":"protein"},
              {"name":"Mashed Potatoes","role":"side","type":"starch"}]'
        meal_type: "dinner", "lunch", "breakfast", or "snack" (default "dinner").
        effort: Infer from context — "low" (≤30min), "medium" (30-60min), "high" (60min+).
        tags: JSON array (lowercase) — ALWAYS include occasion + cuisine + descriptors.
              e.g. '["snack","sweet","bakery","american"]'
        date: Date in YYYY-MM-DD format. Defaults to today.
        logged_by: Who is logging this (default "user").
        notes: Optional notes about the meal.

    Returns:
        Summary of what was logged, created, and updated in the meal library.

    Ack: Logging meal and updating library...
    """
    from datetime import date as _date

    try:
        component_list = json.loads(components) if isinstance(components, str) else components
    except (json.JSONDecodeError, TypeError):
        return "Error: components must be a valid JSON array."

    if not component_list:
        return "Error: at least one component with role='main' is required."

    mains = [c for c in component_list if c.get("role") == "main"]
    sides = [c for c in component_list if c.get("role") != "main"]

    if not mains:
        return "Error: exactly one component must have role='main'. Set role='main' on the primary dish."
    if len(mains) > 1:
        return "Error: only one component can be role='main'. Designate the others as role='side'."

    if meal_type not in ("dinner", "lunch", "breakfast", "snack"):
        meal_type = "dinner"

    try:
        tag_list = json.loads(tags) if isinstance(tags, str) else (tags or [])
    except (json.JSONDecodeError, TypeError):
        tag_list = []
    # Always ensure the meal_type occasion is in the tag list
    if meal_type not in tag_list:
        tag_list.append(meal_type)

    effort_val = effort.strip() if effort in ("low", "medium", "high") else None

    logged_date = date.strip() if date and date.strip() else _date.today().isoformat()

    actions = []

    # Find or create the main component
    main_spec = mains[0]
    main_comp = _dl.find_component_by_name(main_spec["name"])
    if not main_comp:
        comp_id = f"mc-{uuid.uuid4().hex[:8]}"
        main_comp = _dl.create_component(
            component_id=comp_id,
            name=main_spec["name"].strip(),
            comp_type=main_spec.get("type", "protein"),
            by=logged_by,
        )
        actions.append(f"Created component: **{main_comp['name']}** ({comp_id}, {main_comp['type']})")
    else:
        actions.append(f"Found existing component: **{main_comp['name']}** ({main_comp['id']})")

    # Find or create side components
    side_comps = []
    for side_spec in sides:
        side_comp = _dl.find_component_by_name(side_spec["name"])
        if not side_comp:
            comp_id = f"mc-{uuid.uuid4().hex[:8]}"
            side_comp = _dl.create_component(
                component_id=comp_id,
                name=side_spec["name"].strip(),
                comp_type=side_spec.get("type", "other"),
                by=logged_by,
            )
            actions.append(f"Created component: **{side_comp['name']}** ({comp_id}, {side_comp['type']})")
        else:
            actions.append(f"Found existing component: **{side_comp['name']}** ({side_comp['id']})")
        side_comps.append(side_comp)

    candidate_meals = _build_meal_match_candidates(main_spec["name"], main_comp["id"])
    exact_candidate = next(
        (c["meal"] for c in candidate_meals if "exact name" in c["sources"]),
        None,
    )

    description_parts = [main_comp["name"]] + [s["name"] for s in side_comps]
    description = ", ".join(description_parts)

    matched_meal = None
    if candidate_meals:
        matched_meal = _match_meal_with_llm(
            main_comp["name"],
            [s["name"] for s in side_comps],
            candidate_meals,
        )
        if not matched_meal and exact_candidate:
            matched_meal = exact_candidate
    if matched_meal:
        meal = matched_meal
        meal_id = meal["id"]
        # Link main component if not already linked (e.g., meal was created manually without components)
        _dl.link_component_to_meal(meal_id, main_comp["id"], role="main")
        for side_comp in side_comps:
            added = _dl.link_component_to_meal(meal_id, side_comp["id"], role="side")
            if added:
                actions.append(f"Added new side **{side_comp['name']}** to meal **{meal['name']}**")
        candidate_info = next((c for c in candidate_meals if c["meal"]["id"] == meal_id), None)
        source_str = ", ".join(candidate_info["sources"]) if candidate_info else "candidate search"
        actions.append(f"Matched existing meal via {source_str}: **{meal['name']}** ({meal_id})")
    else:
        # New main dish — create a new meal
        meal_name = main_comp["name"]
        meal_id = f"ml-{uuid.uuid4().hex[:8]}"
        _dl.create_meal(
            meal_id=meal_id, name=meal_name, created_by=logged_by,
            effort=effort_val or "medium",
            tags=tag_list,
        )
        _dl.link_component_to_meal(meal_id, main_comp["id"], role="main")
        for side_comp in side_comps:
            _dl.link_component_to_meal(meal_id, side_comp["id"], role="side")
        actions.append(f"Created new meal: **{meal_name}** ({meal_id})")

    # Log dinner entry
    log_id = f"dl-{uuid.uuid4().hex[:8]}"
    _dl.create_meal_log(
        log_id=log_id,
        logged_date=logged_date,
        description=description,
        logged_by=logged_by,
        meal_id=meal_id,
        notes=notes.strip() if notes else "",
        meal_type=meal_type,
    )

    logger.info("MEALS: %s logged for %s: %s (%s)", meal_type.capitalize(), logged_date, description, log_id)

    lines = [f"✅ {meal_type.capitalize()} logged for **{logged_date}**: {description}"]
    lines.append("\nLibrary updates:")
    for a in actions:
        lines.append(f"  • {a}")
    return "\n".join(lines)


def get_meal_log(days: int = 14, meal_type: str = "") -> str:
    """Show recent meal log entries (dinners, lunches, or both).

    Args:
        days: Number of days to look back (default 14).
        meal_type: Filter by "dinner", "lunch", "breakfast", "snack", or leave blank for all.

    Returns:
        Formatted meal log with dates, types, and meals.

    Ack: Loading meal log...
    """
    entries = _dl.get_meal_log(days=days, meal_type=meal_type)
    if not entries:
        filter_str = f" ({meal_type})" if meal_type else ""
        return f"No meals logged in the last {days} days{filter_str}."

    lines = [f"Meal log — last {days} days ({len(entries)} entries):\n"]
    for e in entries:
        type_badge = f"[{e['meal_type']}] " if e.get("meal_type") else ""
        meal_ref = f" → **{e['meal_name']}**" if e.get("meal_name") else ""
        notes_str = f" — {e['notes']}" if e.get("notes") else ""
        lines.append(f"• **{e['logged_date']}** {type_badge}{e['description']}{meal_ref}{notes_str}")
    return "\n".join(lines)


def list_meal_tags() -> str:
    """List all available meal tags with usage counts.

    Returns:
        Formatted tag list.
    """
    tags = _dl.list_tags(with_counts=True)
    if not tags:
        return "No tags defined."
    lines = ["Meal tags:"]
    for t in tags:
        count = t.get("usage_count", 0)
        lines.append(f"• {t['name']} ({count} meals)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dynamic guide context (not an MCP tool — no docstring)
# ---------------------------------------------------------------------------

def get_guide_context() -> str:
    try:
        tags = _dl.tag_cloud()
        if not tags:
            return ""
        # Split into cuisine-like vs descriptor tags heuristically
        _KNOWN_CUISINES = {
            "american", "italian", "mexican", "asian", "indian", "mediterranean",
            "japanese", "southern", "thai", "greek", "french", "chinese", "korean",
            "vietnamese", "tex-mex", "bbq", "middle-eastern", "cajun", "caribbean",
            "spanish", "german", "british", "irish", "eastern-european",
        }
        _KNOWN_OCCASIONS = {"breakfast", "lunch", "dinner", "snack", "any meal"}
        cuisines = sorted([t["name"] for t in tags if t["name"] in _KNOWN_CUISINES])
        occasions = sorted([t["name"] for t in tags if t["name"] in _KNOWN_OCCASIONS])
        descriptors = sorted([t["name"] for t in tags
                               if t["name"] not in _KNOWN_CUISINES
                               and t["name"] not in _KNOWN_OCCASIONS])
        lines = [
            "## Current meal tags",
            "**REQUIRED for every meal — all three categories, all lowercase:**\n",
        ]
        if cuisines:
            lines.append(f"**1. Cuisine** (pick ≥1): {', '.join(cuisines)}")
        if occasions:
            lines.append(f"**2. Occasion** (pick all that apply — not just the logged meal_type): {', '.join(occasions)}")
        if descriptors:
            lines.append(f"**3. Descriptors** (pick ≥1): {', '.join(descriptors)}")
        lines.append("\nYou may add a new tag if nothing here fits — keep it short and reusable.")
        return "\n".join(lines)
    except Exception:
        return ""
