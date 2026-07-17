# Meals App — Tool Guide

## Two separate concepts — never confuse these

### Meal idea (the library)
A reusable entity in the `meals` table. Represents a dish you know how to make / have made. Has components, effort level, and tags. Example: "Grilled Chicken". Tags describe what the meal IS — its cuisine(s), what occasions it suits, and its character.

### Meal log entry (the event)
An event in the `meal_log` table. Records what was actually eaten on a specific date, at a specific meal type (breakfast/lunch/dinner/snack). Points at a meal idea.

**`log_meal()` creates a log entry AND grows the library as a side effect** — it finds or creates the meal idea, then records the event. This is the right tool when the user ate something.

**`add_meal()` only touches the library** — no log entry. Use when adding a meal idea without logging consumption (e.g. "add chicken parmesan to my meal ideas").

**Hard rule: if the user says "meal idea", treat it as library-only.** Do not ask whether they ate it. Phrases like "a meal idea for dinner is ..." mean to find or create the reusable meal and update its components/tags. Words like `dinner`, `lunch`, `breakfast`, or `snack` inside a meal idea request describe what occasions the meal suits; they do NOT mean it was eaten today.

## Tagging rules — read this first

Tags are the **only** classification system for meals. There is no separate cuisine field.
Every meal in the library needs all three tag categories:

### 1. Cuisine tag(s) — required, ≥1
What culinary tradition does this meal belong to? Use lowercase, simple words.
- `american`, `italian`, `mexican`, `asian`, `indian`, `mediterranean`, `japanese`, `southern`, `thai`, `greek`, `french`, `chinese`, `korean`, `bbq`, `tex-mex`, etc.
- A meal can have multiple: `["italian", "american"]` for something like pizza rolls.

### 2. Occasion tag(s) — required, ≥1
When would this meal realistically be eaten? Tag **all** occasions that apply — the meal library is reusable, not tied to one logged event.
- `breakfast`, `lunch`, `dinner`, `snack`
- A meal like Grilled Chicken should have `["dinner", "lunch"]` because you'd eat it at either.
- A muffin should have `["breakfast", "snack"]`.
- `any meal` is valid for something truly universal (crackers, fruit, etc.).
- When logging via `log_meal()`, the current `meal_type` is auto-added — but also include other occasions the meal suits.

### 3. Descriptor tag(s) — required, ≥1
Cooking method, dietary trait, or character. Pick what fits:
- **Method**: `grilled`, `baked`, `fried`, `slow-cooker`, `no-cook`, `steamed`
- **Dietary**: `vegetarian`, `vegan`, `gluten-free`, `dairy-free`, `healthy`
- **Character**: `comfort food`, `kid-friendly`, `quick`, `sweet`, `savory`, `spicy`, `indulgent`, `weeknight`, `weekend`, `crowd-pleaser`
- **Style**: `sandwich`, `pasta`, `rice`, `soup`, `salad`, `bakery`, `protein`

### Tag selection priority
1. **Prefer existing tags** — the "Current meal tags" section at the bottom of this guide lists every tag currently in use. Reuse them whenever they fit.
2. **Invent sparingly** — only add a new tag if nothing in the existing list fits. Keep new tags lowercase, short, and reusable.

### Examples
| Meal | Tags |
|------|------|
| Spaghetti Bolognese | `["dinner","italian","pasta","comfort food","weeknight"]` |
| Breakfast tacos | `["breakfast","mexican","quick","kid-friendly"]` |
| Biscuits & chocolate gravy | `["breakfast","american","southern","comfort food","sweet"]` |
| Grilled chicken + sides | `["dinner","lunch","american","grilled","weeknight","healthy"]` |
| PB&J sandwich | `["lunch","snack","american","quick","kid-friendly","no-cook","sandwich"]` |
| Chocolate muffin | `["breakfast","snack","american","sweet","bakery"]` |

---

## Primary workflow: logging what we ate

This is the most common and important use case. When the user clearly says what was eaten — responding to the 9pm dinner prompt with what they had, mentioning a lunch they ate, or describing a snack they just had — **call `log_meal()`**.

Do **not** use this workflow for meal ideas, saved meals, or suggestions for a future meal. Those belong in the library-only `add_meal()` path.

`log_meal()` records **what was eaten** (the event). As a side effect it also finds or creates the meal idea in the library. You don't have to call anything else to grow the library — just log the meal.

### Step-by-step
1. Identify the components: what's the **main dish**? What are the **sides**?
2. Call `log_meal()` — pass `meal_type` for the occasion being logged. Internally it will:
   - **Look up** whether the main dish already exists as a meal in the library
   - **Build candidate matches from two paths**: fuzzy meal-name search and main-component search
   - **Ask the matcher to compare those candidates logically** before deciding whether to reuse or create
   - **If a candidate is a good fit** — use that existing meal; add any new sides to it
   - **If nothing fits** — create the meal idea first, then link all components
   - **Finally** — create the meal log entry (the event) pointing at that meal
3. If the user mentions quality or rating ("it was amazing", "pretty good"), call `rate_meal()` immediately after.
4. **Always infer and pass** `effort` and `tags` — do not leave them blank.
5. `tags` go on the **meal idea** in the library. Include all occasions the meal suits (not just the current one), its cuisine(s), and descriptors.

### Example: "We had grilled chicken with mashed potatoes and green beans tonight"
```
log_meal(
  components='[
    {"name":"Grilled Chicken","role":"main","type":"protein"},
    {"name":"Mashed Potatoes","role":"side","type":"starch"},
    {"name":"Green Beans","role":"side","type":"vegetable"}
  ]',
  meal_type="dinner",
  effort="medium",
  tags='["dinner","american","grilled","weeknight"]'
)
```

### Example: "Had a PB&J for lunch"
```
log_meal(
  components='[{"name":"PB&J Sandwich","role":"main","type":"other"}]',
  meal_type="lunch",
  effort="low",
  tags='["lunch","american","quick","kid-friendly"]'
)
```

### Example: "Had some chips and salsa as a snack"
```
log_meal(
  components='[
    {"name":"Chips","role":"main","type":"other"},
    {"name":"Salsa","role":"side","type":"sauce"}
  ]',
  meal_type="snack",
  effort="low",
  tags='["snack","american","savory","quick"]'
)
```

### Example: "Had a chocolate muffin as a snack"
```
log_meal(
  components='[{"name":"Chocolate Muffin","role":"main","type":"other"}]',
  meal_type="snack",
  effort="low",
  tags='["snack","sweet","bakery","american"]'
)
```

### Example: "Had biscuits and chocolate gravy for breakfast"
```
log_meal(
  components='[
    {"name":"Biscuits","role":"main","type":"bread"},
    {"name":"Chocolate Gravy","role":"side","type":"sauce"}
  ]',
  meal_type="breakfast",
  effort="medium",
  tags='["breakfast","american","southern","sweet","comfort food"]'
)
```

### meal_type values
| value | when to use |
|-------|-------------|
| `dinner` | evening meal (default, used for 9pm prompt) |
| `lunch` | midday meal |
| `breakfast` | morning meal |
| `snack` | anytime snack |

### Component roles
- **main** — exactly ONE per meal: the primary dish (protein, sandwich, pasta, etc.)
- **side** — everything else: sides, accompaniments, sauces, garnishes

### Component types (for creation)
`protein` · `starch` · `vegetable` · `sauce` · `grain` · `bread` · `dairy` · `fruit` · `other`

## Key rule: how the meal library grows
- The **main component is matched exactly** (case-insensitive). "Grilled Chicken" is always "Grilled Chicken".
- Each unique main dish is ONE meal idea in the library.
- **Side dishes accumulate** — every new side you mention gets added to that meal idea.
- This means the library grows naturally without creating thousands of combinations.
- You never duplicate components — each component is created once and reused.

## Meal discovery workflow

When the user asks "what should we eat?" or "what's something easy tonight?":

1. Use `find_meals()` with filters, OR `list_all_meals()` to browse
2. Get details with `get_meal()` to show components and info
3. Suggest 2-3 options based on filters

## Cleaning up the library — CONFIRM before deleting

The library has full CRUD, including destructive cleanup. Before ANY delete or merge,
**show the exact record(s) and get the user's explicit confirmation** — never delete or
merge on your own initiative or from a vague request.

- **Duplicate meal?** Prefer `merge_meals(keep_id, duplicate_id)` over deleting — it moves
  the duplicate's components, dinner-log history, photos, and tags onto the keeper so no
  history is lost, then removes the duplicate. Show BOTH meals (`get_meal`) and confirm
  which id to keep vs. remove.
- **Delete a meal** (`delete_meal`) only for a genuine mistake with nothing worth keeping.
  Show it (`get_meal`) and confirm first. Its component links + photos go with it; dinner-log
  history is kept but unlinked.
- **Delete a component** (`delete_component`) — a component still used by any meal can't be
  deleted; the tool reports which meals use it. Remove it from those meals first
  (`remove_component_from_meal`), then confirm and delete.
- **Fix vs. remove:** to correct a component use `update_component`; to change a meal's
  makeup use `add_component_to_meal` / `remove_component_from_meal` — don't delete and recreate.

## Tool reference

### log_meal(components, meal_type, effort, tags, date, logged_by, notes)
**Primary logging tool.** Use whenever someone mentions what they ate.
- `components`: JSON array — each item has `name`, `role` ("main"/"side"), optional `type`
- `meal_type`: "dinner" | "lunch" | "breakfast" | "snack" — defaults to "dinner"
- `effort`: **always infer** — "low" (≤30min/no cooking), "medium" (30-60min), "high" (60min+)
- `tags`: **always populate, all lowercase** — must cover all three categories (see Tagging rules above):
  - **Cuisine** (≥1): `"american"`, `"italian"`, `"mexican"`, etc.
  - **Occasion** (≥1): include `meal_type` + any other occasions this meal suits. e.g. grilled chicken logged as dinner should also get `"lunch"` since you'd eat it then too.
  - **Descriptors** (≥1): `"comfort food"`, `"kid-friendly"`, `"quick"`, `"grilled"`, `"sweet"`, `"savory"`, etc.
  - **See "Current meal tags" section below** — always prefer tags already in use over new ones
- `date`: YYYY-MM-DD, defaults to today
- Multiple entries of the same type are allowed (two snacks, two lunches, etc.) — each gets its own log entry

### check_today_meals()
Check what's already been logged today. Use when user asks "what have I eaten today?" or before logging to avoid duplicates.

### get_meal_log(days, meal_type)
Show recent meal history. `days` defaults to 14. Filter by `meal_type` or leave blank for all.

### rate_meal(meal_id, rating, by)
Rate a meal 1-5 stars. Call immediately if user expresses satisfaction: "that was delicious" → 5, "it was okay" → 3.

### update_meal(meal_id, by, name, effort, tags, description, notes, rating)
Update any meal metadata. Only fields you provide are changed. Cuisine is part of the tags array.
```
update_meal("ml-abc123", effort="medium", tags='["american","weeknight","grilled"]')
```

### find_meals(filters)
Primary discovery tool. Pass a JSON array of filter objects. Use `type:"tag"` for cuisine filtering too.
If the user says a hashtag like `#snack`, pass the tag value as `snack` (the tools also normalize the leading `#`).
```
find_meals('[{"type":"effort","mode":"include","value":"low"},{"type":"tag","mode":"exclude","value":"mexican"}]')
```

### list_all_meals(effort, q, tag)
Browse the full library. Optional simple filters, tag filter, or name search.

### random_meals(count, tag, effort, filters)
Pick random meal ideas from the library. Use this for "random meal", "surprise me", or requests for a number of options.
For "3 random #snack options", call `random_meals(count=3, tag="snack")`.

### get_meal(meal_id)
Full details for a meal: components (sorted by role), tags, effort, cuisine, rating.

### add_meal(name, created_by, effort, tags, description, notes, rating)
Manually add a meal to the library. Prefer `log_meal()` for meals you actually ate — it handles component creation automatically. Use `add_meal()` only when adding to the library without logging consumption. Tags must include a lowercase cuisine tag.

### list_components(q, type_filter)
List reusable components. Filter by type: protein, starch, vegetable, sauce, grain, bread, dairy, fruit, other.

### add_component(name, comp_type, description, tags, recipe_id, by)
Add a new reusable component. Prefer the automatic creation in `log_meal()`. Use this only for explicit standalone component additions.

### list_meal_tags()
List all tags with usage counts (includes cuisine tags).

### update_component(component_id, name, comp_type, description, tags, by)
Fix or re-type an existing component (e.g. a typo, or "other" → "protein"). Only fields you pass change.

### add_component_to_meal(meal_id, component_id, role)
Link an existing component onto a meal. role: main | side | sauce | garnish | other.

### remove_component_from_meal(meal_id, component_id)
Unlink a component from a meal. The component itself stays in the library.

### delete_meal(meal_id, by) — DESTRUCTIVE
Delete a meal (a duplicate or mistake). Component links + photos go with it; dinner-log history is kept but unlinked. **Confirm with the user first** (show it via get_meal). To keep a duplicate's history, prefer merge_meals.

### merge_meals(keep_id, duplicate_id, by) — DESTRUCTIVE
Fold a duplicate meal into the keeper (moves its components, dinner-log history, photos, tags), then delete the duplicate. **Confirm with the user first**, showing BOTH meals.

### delete_component(component_id, by) — DESTRUCTIVE
Delete a reusable component. Refuses if any meal still uses it (reports which). **Confirm with the user first.**

## Effort levels
- **low** — ≤30 min, minimal prep (sandwiches, simple pasta, heating soup)
- **medium** — 30-60 min, moderate cooking (tacos, stir-fry, homemade pizza)
- **high** — 60+ min or complex (roasts, slow-cooker, multi-step recipes)

## Filter reference
| type | example values |
|------|---------------|
| tag | cuisine ("mexican", "italian", "american"), occasion ("breakfast", "lunch", "dinner", "snack"), or descriptor ("kid-friendly", "vegetarian", "weeknight", "grilled", "comfort food", "spicy") |
| effort | "low", "medium", "high" |
| component | partial name like "potatoes", "chicken" |

## Natural language patterns

### Intent: did the user EAT it, or just SUGGEST it?
- Phrases like **"we had", "I ate", "I had", "we ate", "we had this for dinner tonight", "I had this for lunch", "I ate this as a snack"** → user ate it → `log_meal()`
- Phrases like **"here is a meal idea", "a meal idea for dinner is ...", "dinner idea: ...", "add this to my meal ideas", "save this as a meal", "I want to remember this meal"** → user did NOT eat it → `add_meal()` only, **no log entry**
- If the phrase **"meal idea"** appears anywhere, that is decisive: use `add_meal()` and do not ask whether to log it.
- In meal idea requests, meal words like **`dinner`**, **`lunch`**, **`breakfast`**, and **`snack`** are tagging hints for the reusable meal, not evidence that it was eaten today.
- Only ask a clarifying question when the user gives a meal with neither an "ate it" signal nor a "meal idea/save it" signal. Never ask the eat-vs-save follow-up when the user already said "meal idea".

### Logging meals (user ate it)
- "We had grilled chicken with rice and broccoli" → `log_meal()` dinner, main=Grilled Chicken
- "I had a sandwich for lunch" → `log_meal()` lunch, main=Sandwich
- "Had scrambled eggs and toast this morning" → `log_meal()` breakfast, main=Scrambled Eggs, side=Toast
- "Just had some apple slices as a snack" → `log_meal()` snack, main=Apple Slices
- "That was amazing!" (after logging) → `rate_meal()` with 5 stars
- "What did I eat today?" → `check_today_meals()`
- "What have we been eating lately?" → `get_meal_log(days=14)`

### Discovery
- When the user asks for meal ideas/options "for" a type, category, cuisine, occasion, mood, or descriptor, first treat that word as a likely meal tag. Examples: `snack`, `dinner`, `lunch`, `quick`, `no-cook`, `vegetarian`, `comfort food`, `mexican`, `sweet`.
- If the requested type is not an obvious exact tag, call `list_meal_tags()` and choose the closest existing tag before filtering. Prefer existing tags over inventing a new category.
- For a small number of suggestions, use `random_meals(count=N, tag=...)`. For browsing all matches, use `list_all_meals(tag=...)` or `find_meals()`.
- "What should we have for dinner?" → `find_meals()` with no filters or relevant ones
- "Something fast tonight" → `find_meals([{"type":"effort","mode":"include","value":"low"}])`
- "No Mexican tonight" → `find_meals([{"type":"tag","mode":"exclude","value":"mexican"}])`
- "Something kid-friendly" → `find_meals([{"type":"tag","mode":"include","value":"kid-friendly"}])`
- "What can we make with chicken?" → `find_meals([{"type":"component","mode":"include","value":"chicken"}])`
- "Show me all our Italian meals" → `list_all_meals(tag="italian")`
- "Give me 3 random #snack options" → `random_meals(count=3, tag="snack")`
- "Surprise me with a random dinner idea" → `random_meals(count=1, tag="dinner")`

### Library management (meal ideas — no log entry)
- "Here is a meal idea: Cappuccino with cinnamon sugar" → `add_meal(name="Cappuccino", components='[{"name":"Cappuccino","role":"main","type":"other"},{"name":"Cinnamon Sugar Sprinkles","role":"side","type":"other"}]', tags='["snack","breakfast","american","sweet","coffee"]', effort="low")`
- "Add Chicken Parmesan to my meal ideas" → `add_meal(name="Chicken Parmesan", components='[{"name":"Chicken Parmesan","role":"main","type":"protein"}]', tags='["dinner","italian","comfort food"]', effort="medium")`
- "A meal idea for dinner is herbed noodles, rice pilaf, and corn or carrots" → `add_meal()` only. Look up the existing meal by main dish (`Herbed Noodles`), add any new sides, and keep this as a reusable dinner meal. Do **not** ask whether to log it unless the user explicitly says they ate it.
- "That meal already exists" → `add_meal()` still works — it finds the existing meal and merges in any new tags/components
- "Rate last night's dinner 4 stars" → `rate_meal(meal_id, 4)`
- "Mark that as low effort" → `update_meal(meal_id, effort="low")`
- "Add the tag weeknight to that meal" → `update_meal(meal_id, tags='["weeknight","american"]')`

### Cleanup (confirm the record first, then delete/merge)
- "We have Chicken Tacos twice" → show both with `get_meal`, confirm which to keep → `merge_meals(keep_id, duplicate_id)`
- "Delete that meal, it was a mistake" → show it with `get_meal`, confirm → `delete_meal(meal_id)`
- "Add mashed potatoes as a side to that" → `add_component_to_meal(meal_id, component_id, role="side")`
- "Take the rice off that meal" → `remove_component_from_meal(meal_id, component_id)`
- "That component name is misspelled" → `update_component(component_id, name="…")`
- "Delete the Salsa Verde component" → `delete_component(component_id)` (it will refuse + list meals if still used)
