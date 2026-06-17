#!/usr/bin/env python3
"""Generate a reverse-engineered C/F/S draft tree (EVOLVE.md §12) from a compact JSON description.

Emits specs/<app>/_capability.yaml + <feature>/_feature.yaml + <feature>/<spec>.yaml — all
`state: proposed`, `tests: []`, flagged as drafts that describe CURRENT code behavior and need human
review + bound tests before `live`. Keeps the field shape identical across every app so the whole
corpus is consistent and passes `python3 -m apps.evolve.schema specs/<app>`.

Input JSON shape:
{
  "app": "reminders", "title": "Reminders",
  "scope": "what it IS … NOT …",
  "features": [
    {"id": "set", "title": "Setting reminders & nags",
     "specs": [
       {"id": "set-reminder", "title": "Set a reminder",
        "behavior": "…current behavior…",
        "implements": ["apps/reminders/tools.py"]}      # optional; defaults to apps/<app>/tools.py
     ]}
  ]
}

  python scripts/cfs_draft.py specs_drafts/reminders.json
"""
import json, os, sys, yaml

NOTES = ("Reverse-engineered draft (EVOLVE.md §12): describes current code behavior; "
         "needs human review + bound tests before `live`.")


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(obj, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=92)
    print("  wrote", path)


def main():
    tree = json.load(open(sys.argv[1]))
    app = tree["app"]
    root = f"specs/{app}"
    dump(f"{root}/_capability.yaml", {
        "kind": "capability", "id": app, "title": tree["title"], "app": app,
        "scope": tree["scope"], "state": "proposed",
        "autonomy": tree.get("autonomy", "gated"), "links": {}, "notes": NOTES,
    })
    for feat in tree["features"]:
        fid = f"{app}.{feat['id']}"
        fdir = f"{root}/{feat['id']}"
        dump(f"{fdir}/_feature.yaml", {
            "kind": "feature", "id": fid, "title": feat["title"],
            "state": "proposed", "links": {}, "notes": NOTES,
        })
        for spec in feat["specs"]:
            sid = f"{fid}.{spec['id']}"
            dump(f"{fdir}/{spec['id']}.yaml", {
                "kind": "specification", "id": sid, "title": spec["title"],
                "state": "proposed", "autonomy": spec.get("autonomy", "gated"),
                "behavior": spec["behavior"],
                "implements": spec.get("implements", [f"apps/{app}/tools.py"]),
                "tests": [], "links": {}, "notes": NOTES,
            })
    print(f"done: {root}  ({sum(len(f['specs']) for f in tree['features'])} specs in "
          f"{len(tree['features'])} features)")


if __name__ == "__main__":
    main()
