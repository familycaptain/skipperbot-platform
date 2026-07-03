#!/usr/bin/env python3
"""tool_policy_harness.py — test the LEAN tool-loading POLICY in isolation, with MOCKED tools,
across scripted conversations, using the real chat model (SMART_MODEL). NO production loop is
touched. We watch what the model CHOOSES to load/unload and what the prompt costs.

Policy under test ("category slots, LLM-chosen, auto-swap"):
  - Always-on core = META tools only (request_tools / unload_tools / list_categories). No
    guide-bearing domain tools in core (a tool without its guide gets misused).
  - The model loads a category into one of N SLOTS when it decides it needs it. Loading when
    slots are full auto-evicts the OLDEST (visible). The model may also unload_tools to free a
    slot. Each load returns the category's GUIDE (tools+guide travel together).
  - The system prompt always states which categories are currently loaded.

What we measure per turn: prompt tokens, loaded slots, load/unload events ("tool bubbles"),
which mock domain tools fired, and the final reply. The question: does the model load the
RIGHT category at the right moment (including a back-reference like "now do it") and keep
tokens flat — i.e., is intelligence a good enough router?

Run in the box2 agent container (has OPENAI key + the openai client):
    docker compose exec -T agent python scripts/tool_policy_harness.py
    docker compose exec -T agent python scripts/tool_policy_harness.py --slots 1
"""
import argparse
import json
import os
import sys

# Run as `python scripts/X.py` from the repo root (/app in the container): make the repo root
# importable so `config` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dev harness: resolve the SMART tier's connector+model+key (MODEL_FLEXIBILITY #44/#71) instead
# of the removed config.openai_client / the OPENAI_API_KEY env assumption.
from providers.tier_resolver import resolve_chat as _resolve_chat
_smart_provider, SMART_MODEL, _smart_key = _resolve_chat("smart")
openai_client = _smart_provider._get_client(_smart_key)

# ---------------------------------------------------------------------------
# Mock category universe — mirrors Skipper's real apps (names matter; schemas are stubs).
# Each: short catalog desc, a few mock tools, and a one-line guide (what request_tools returns).
# ---------------------------------------------------------------------------
CATEGORIES = {
    "reminders":  {"desc": "timed reminders & nags", "guide": "Reminders: use set_reminder(text, when[, recur]). 'when' is natural language; recurring needs an explicit cadence.",
                   "tools": [("set_reminder", {"text": "string", "when": "string", "recur": "string"}), ("cancel_reminder", {"id": "string"})]},
    "chores":     {"desc": "kids' chore rotations & check-off", "guide": "Chores: add_chore(name, assignee_or_rotation, days). For a rotation pass rotation='weekly' and the kids will alternate.",
                   "tools": [("add_chore", {"name": "string", "rotation": "string", "days": "string"}), ("complete_chore", {"id": "string"})]},
    "meals":      {"desc": "meal ideas & weekly dinner plans", "guide": "Meals: suggest_meals(filters) or plan_week(nights). Filter by effort/cuisine/tags.",
                   "tools": [("suggest_meals", {"filters": "string"}), ("plan_week", {"nights": "integer"})]},
    "recipes":    {"desc": "family recipe collection", "guide": "Recipes: create_recipe(title, ingredients[], steps[]). Ingredients are structured strings.",
                   "tools": [("create_recipe", {"title": "string", "ingredients": "array", "steps": "array"}), ("find_recipe", {"q": "string"})]},
    "lists":      {"desc": "shopping/to-do lists (Trello-synced)", "guide": "Lists: add_list_item(list, item) / create_list(name). A list may be Trello-synced.",
                   "tools": [("create_list", {"name": "string"}), ("add_list_item", {"list": "string", "item": "string"})]},
    "goals":      {"desc": "goals/projects/tasks (PM)", "guide": "Goals: create_goal/create_project/create_task. Tasks live under projects under goals.",
                   "tools": [("create_goal", {"name": "string"}), ("create_task", {"project": "string", "name": "string"})]},
    "auto":       {"desc": "vehicle maintenance schedules", "guide": "Auto: add_vehicle(name) / add_schedule(vehicle, item, interval). Intervals can be mileage or time.",
                   "tools": [("add_vehicle", {"name": "string"}), ("add_schedule", {"vehicle": "string", "item": "string", "interval": "string"})]},
    "weather":    {"desc": "weather & forecasts", "guide": "Weather: get_current_weather([location]) — omit location for the saved home.",
                   "tools": [("get_current_weather", {"location": "string"})]},
    "medical":    {"desc": "meds, treatments, lab trends", "guide": "Medical: add_medication(name, dose, cadence).",
                   "tools": [("add_medication", {"name": "string", "dose": "string", "cadence": "string"})]},
    "home":       {"desc": "appliances & home repairs", "guide": "Home: add_appliance(name) / log_repair(appliance, note).",
                   "tools": [("add_appliance", {"name": "string"}), ("log_repair", {"appliance": "string", "note": "string"})]},
    "settings":   {"desc": "household setup: members, location, integrations", "guide": "Settings: add_member(name, role) / set_location(place). Family/location/integrations live here.",
                   "tools": [("add_member", {"name": "string", "role": "string"}), ("set_location", {"place": "string"})]},
}

CORE_HINT = (
    "You are Skipper, a warm family assistant. You have a LARGE toolset, but tools load in "
    f"a few CATEGORY SLOTS so your context stays lean.\n"
    "RULES:\n"
    "- You start with only the meta-tools. To act in a domain, call request_tools(category) — "
    "it loads that category's tools AND its usage guide. Then use them right away.\n"
    "- Loading when slots are full auto-unloads your OLDEST category. You can also "
    "unload_tools(category) to free a slot yourself.\n"
    "- Use the conversation (it's all here) to decide which category you need NOW. If the user "
    "refers back to an earlier topic ('do it'), load THAT topic's category. Never invent a tool "
    "you don't have loaded — load its category first.\n"
)


def _meta_tools():
    cat_list = ", ".join(f"{c} ({d['desc']})" for c, d in CATEGORIES.items())
    return [
        {"type": "function", "function": {"name": "request_tools", "description": f"Load a category's tools+guide into a slot. Categories: {cat_list}.",
            "parameters": {"type": "object", "properties": {"category": {"type": "string"}}, "required": ["category"]}}},
        {"type": "function", "function": {"name": "unload_tools", "description": "Free a slot by unloading a category you no longer need.",
            "parameters": {"type": "object", "properties": {"category": {"type": "string"}}, "required": ["category"]}}},
    ]


def _domain_schema(tool_name, params):
    return {"type": "function", "function": {"name": tool_name, "description": f"(mock) {tool_name}",
            "parameters": {"type": "object", "properties": {k: {"type": v if v != "array" else "array"} for k, v in params.items()}}}}


class Policy:
    def __init__(self, slots):
        self.cap = slots
        self.loaded = []          # ordered, oldest first

    def load(self, cat):
        if cat not in CATEGORIES:
            return None, None, f"'{cat}' is not a category."
        if cat in self.loaded:
            return cat, None, None
        evicted = None
        if len(self.loaded) >= self.cap:
            evicted = self.loaded.pop(0)
        self.loaded.append(cat)
        return cat, evicted, None

    def unload(self, cat):
        if cat in self.loaded:
            self.loaded.remove(cat)
            return cat
        return None

    def tools(self):
        t = _meta_tools()
        for cat in self.loaded:
            for name, params in CATEGORIES[cat]["tools"]:
                t.append(_domain_schema(name, params))
        return t

    def system(self):
        loaded = ", ".join(self.loaded) if self.loaded else "(none)"
        return CORE_HINT + f"\nSLOTS: {self.cap}. CURRENTLY LOADED: {loaded}."


def run_script(name, turns, slots):
    pol = Policy(slots)
    print(f"\n{'='*78}\nSCRIPT: {name}  (slots={slots})\n{'='*78}")
    history = []
    max_prompt = 0
    for ti, user in enumerate(turns, 1):
        print(f"\n--- turn {ti} ---\nYOU: {user}")
        history.append({"role": "user", "content": user})
        # mini agent loop
        for _hop in range(8):
            messages = [{"role": "system", "content": pol.system()}] + history
            resp = openai_client.chat.completions.create(model=SMART_MODEL, messages=messages, tools=pol.tools())
            msg = resp.choices[0].message
            pt = resp.usage.prompt_tokens
            max_prompt = max(max_prompt, pt)
            if not msg.tool_calls:
                print(f"  [prompt {pt:,} tok | loaded: {pol.loaded or '∅'}]")
                print(f"SKIPPER: {(msg.content or '').strip()[:400]}")
                history.append({"role": "assistant", "content": msg.content or ""})
                break
            history.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                fn = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                if fn == "request_tools":
                    cat, evicted, err = pol.load(args.get("category", ""))
                    if err:
                        result = err
                    else:
                        bubble = f"🔵 loaded [{cat}]" + (f"  ⚪ unloaded [{evicted}]" if evicted else "")
                        print(f"  {bubble}  (prompt {pt:,} tok)")
                        result = f"Loaded {cat}. GUIDE: {CATEGORIES[cat]['guide']}"
                elif fn == "unload_tools":
                    u = pol.unload(args.get("category", ""))
                    print(f"  ⚪ unloaded [{u}]")
                    result = f"Unloaded {u}." if u else "not loaded"
                else:  # mocked domain tool
                    print(f"  🛠  {fn}({json.dumps(args)})   [loaded: {pol.loaded}]")
                    result = json.dumps({"ok": True, "mock": fn})
                history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    print(f"\n>>> {name}: MAX prompt tokens = {max_prompt:,} | final loaded = {pol.loaded}")
    return max_prompt


SCRIPTS = {
    "onboarding_then_switch": [
        "hi",
        "It's me (Rodney), my wife Sarah, and our kids Emma (8) and Jack (5). I want help with reminders, the kids' chores, and meal planning.",
        "Let's set up a weekly chore rotation for the kids — Emma and Jack alternate.",
        "Actually first, save my chili recipe: beef, beans, tomato, chili powder; brown the beef then simmer 30 min.",
        "ok now go ahead and do the chores thing we talked about",
        "and remind me trash night every Wednesday at 7pm",
    ],
    # One turn that legitimately needs THREE categories — does 2 slots cope (swap mid-turn) or choke?
    "three_in_one_turn": [
        "Add milk to my shopping list, remind me to buy it tomorrow at 5pm, and save a quick recipe that uses milk (pancakes).",
    ],
    # Back-reference AFTER the category was evicted, where a real ACTION is needed (not just status).
    "backref_after_evict": [
        "set up a chore: feed the dog every morning",
        "now save my taco recipe: tortillas, beef, cheese",
        "what's the weather?",
        "go back to chores and add another one: take out recycling on Saturdays",
    ],
    # Ambiguous 'set that up' with two live topics in play — pick the right one or ask, not guess.
    "ambiguous_that": [
        "I'm thinking about meal planning, and also a reminder for soccer practice Tuesdays at 4.",
        "yeah, set that up",
    ],
    # Rapid topic flips — swap cleanly, stay flat, don't accumulate.
    "rapid_flips": [
        "what's the weather today?",
        "add a chore: water the plants on Sundays",
        "is it going to rain this week?",
        "save a recipe: grilled cheese — bread, butter, cheese",
        "add bananas to the shopping list",
    ],
    # Pure chitchat / questions needing NO tools — should load nothing, stay tiny.
    "no_tools_needed": [
        "hey what can you help me with?",
        "cool. what's the difference between a goal and a project here?",
        "ok thanks",
    ],
    # Deep single-category task across many turns — keep the one category sticky, don't re-load each turn.
    "deep_single_task": [
        "let's build out the kids' chores",
        "add: make bed, daily",
        "add: dishes after dinner, daily",
        "add: vacuum living room, Saturdays",
        "actually make the dishes one weekdays only",
        "and add feed the cat every morning",
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--script", default="")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all or not args.script:
        results = {}
        for name, turns in SCRIPTS.items():
            results[name] = run_script(name, turns, args.slots)
        print("\n" + "=" * 78)
        print(f"SUMMARY (slots={args.slots}) — max prompt tokens per script (eager router was ~173,000):")
        for name, mx in results.items():
            print(f"  {name:<24} {mx:>7,} tok")
    else:
        run_script(args.script, SCRIPTS[args.script], args.slots)


if __name__ == "__main__":
    main()
