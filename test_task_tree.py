#!/usr/bin/env python3
"""Diagnostic: task tree rendering, stack_rank, and auto-nag behavior.

Run:  python3 test_task_tree.py
"""

from apps.goals.store import (
    get_goal_detail, get_user_tasks, get_next_naggable_task,
    _get_tasks_for_project, _get_subtasks, _load_entity,
    _is_task_blocked, _save_entity,
)

ATTUNE_GOAL = "g-eafd1d5a"
ATTUNE_PROJECT = "p-d4569577"
SEP = "=" * 72


def section(num, title):
    print(f"\n{SEP}\n  {num}. {title}\n{SEP}")


# ── 1. Tool output: just the task lines the LLM sees ───────────────────────
def test_tool_output():
    section(1, "TOOL OUTPUT — task lines from get_goal_detail (what LLM sees)")
    output = get_goal_detail(ATTUNE_GOAL)
    for line in output.split("\n"):
        s = line.strip()
        if s.startswith("○") or s.startswith("↳") or s.startswith("►") or s.startswith("✓") or s.startswith("✕"):
            print(f"  {line}")


# ── 2. Tree view with hierarchy + dependencies + blocked status ─────────────
def test_tree():
    section(2, "TASK TREE — hierarchy, global ranks, deps, blocked status")
    all_tasks = _get_tasks_for_project(ATTUNE_PROJECT)
    task_map = {t["id"]: t for t in all_tasks}
    top = sorted([t for t in all_tasks if not t.get("parent_task_id")],
                 key=lambda t: t.get("stack_rank", 0))

    def show(tasks, depth=0):
        for t in tasks:
            rank = t.get("stack_rank", "?")
            st = t.get("status", "?")[:11]
            assigned = ", ".join(t.get("assigned_to", []))
            deps = t.get("depends_on", [])
            dep_str = ""
            if deps:
                parts = [f"#{task_map[d].get('stack_rank','?')}" for d in deps if d in task_map]
                dep_str = f" depends:{','.join(parts)}"
            blocked = " BLOCKED" if _is_task_blocked(t) else ""
            trello = f" [T:{t['trello_list']}]" if t.get("trello_list") else ""
            ind = "    " * depth
            arrow = "↳ " if depth > 0 else ""
            subs = _get_subtasks(t)
            children = f" [{len(subs)} sub]" if subs else ""
            print(f"  {ind}{arrow}#{rank:<3} {st:<11} {t['name'][:50]}{children}{dep_str}{blocked}{trello}")
            if subs:
                show(sorted(subs, key=lambda s: s.get("stack_rank", 0)), depth + 1)

    show(top)
    print(f"\n  {len(all_tasks)} tasks total  |  {len(top)} top-level  |  {len(all_tasks)-len(top)} subtasks")


# ── 3. Flat rank + auto-nag decision for each task ─────────────────────────
def test_flat_autonag_view():
    section(3, "FLAT RANK — auto-nag decision for each task")
    all_tasks = sorted(_get_tasks_for_project(ATTUNE_PROJECT),
                       key=lambda t: t.get("stack_rank", 0))
    for t in all_tasks:
        rank = t.get("stack_rank", "?")
        st = t.get("status", "?")
        parent = t.get("parent_task_id", "")
        sub_tag = " (sub)" if parent else ""
        subs = _get_subtasks(t)

        if st in ("done", "deferred"):
            decision = "SKIP done/deferred"
        elif _is_task_blocked(t):
            decision = "SKIP blocked"
        elif subs:
            if all(s.get("status") in ("done", "deferred") for s in subs):
                decision = "→ ACTIONABLE (wrap-up)"
            else:
                decision = "SKIP has unfinished subs"
        else:
            decision = "→ ACTIONABLE (leaf)"

        name = t["name"][:42]
        print(f"  #{rank:<3} {st:<11} {name:<44}{sub_tag:<7} {decision}")


# ── 4. Rank uniqueness ─────────────────────────────────────────────────────
def test_rank_uniqueness():
    section(4, "RANK UNIQUENESS CHECK")
    all_tasks = _get_tasks_for_project(ATTUNE_PROJECT)
    ranks = [t.get("stack_rank", 0) for t in all_tasks]
    print(f"  Tasks: {len(all_tasks)}  |  Unique ranks: {len(set(ranks))}  |  Range: {min(ranks)}-{max(ranks)}")
    if len(ranks) != len(set(ranks)):
        from collections import Counter
        dupes = {r: c for r, c in Counter(ranks).items() if c > 1}
        for r in dupes:
            names = [t["name"][:40] for t in all_tasks if t.get("stack_rank") == r]
            print(f"  ⚠ DUPE rank {r}: {names}")
    else:
        print(f"  ✅ All ranks unique!")


# ── 5. Current auto-nag target ──────────────────────────────────────────────
def test_autonag_now():
    section(5, "AUTO-NAG — current next naggable task")
    nag = get_next_naggable_task(ATTUNE_PROJECT)
    if nag:
        parent_id = nag.get("parent_task_id")
        parent_note = ""
        if parent_id:
            p = _load_entity(parent_id)
            if p:
                parent_note = f"  (subtask of #{p.get('stack_rank','?')} {p['name'][:30]})"
        print(f"  → #{nag.get('stack_rank')} {nag['name'][:60]}")
        print(f"    Assigned: {nag.get('assigned_to')}  Status: {nag.get('status')}{parent_note}")
    else:
        print("  No actionable task!")


# ── 6. Auto-nag simulation: step through completions ───────────────────────
def test_autonag_sim():
    section(6, "AUTO-NAG SIMULATION — step-by-step (dry run, changes reverted)")
    all_tasks = _get_tasks_for_project(ATTUNE_PROJECT)
    originals = {t["id"]: t.get("status") for t in all_tasks}

    for step in range(1, 16):  # up to 15 steps
        nag = get_next_naggable_task(ATTUNE_PROJECT)
        if not nag:
            print(f"\n  Step {step}: ✗ No more actionable tasks!")
            break

        rank = nag.get("stack_rank", "?")
        parent_id = nag.get("parent_task_id")
        parent_note = ""
        if parent_id:
            p = _load_entity(parent_id)
            if p:
                parent_note = f"  ← subtask of #{p.get('stack_rank','?')} {p['name'][:25]}"

        assigned = ", ".join(nag.get("assigned_to", []))
        print(f"  Step {step:>2}: nag → #{rank:<3} {nag['name'][:45]}  [{assigned}]{parent_note}")

        # Simulate completion
        nag["status"] = "done"
        _save_entity(nag)

        # Check parent wrap-up
        if parent_id:
            p = _load_entity(parent_id)
            if p:
                subs = _get_subtasks(p)
                if all(s.get("status") in ("done", "deferred") for s in subs):
                    print(f"           → all subs of #{p.get('stack_rank','?')} done, parent now actionable")

    # Restore
    for t in _get_tasks_for_project(ATTUNE_PROJECT):
        if t["id"] in originals:
            t["status"] = originals[t["id"]]
            _save_entity(t)
    print(f"\n  ✓ Restored all {len(originals)} tasks to original status.")


if __name__ == "__main__":
    test_tool_output()
    test_tree()
    test_flat_autonag_view()
    test_rank_uniqueness()
    test_autonag_now()
    test_autonag_sim()
