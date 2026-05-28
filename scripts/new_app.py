"""
new_app.py — Scaffold a new skipperbot-app-<name> repo.

Creates a sibling directory `../skipperbot-app-<name>/` with the standard
app skeleton:

    manifest.yaml
    data.py             (with the _HINT pattern + digest_record calls)
    tools.py            (one example tool)
    routes.py           (FastAPI APIRouter scaffold)
    guide.md            (LLM-facing tool category description)
    handlers.py         (event subscriptions stub)
    migrations/001_initial.sql
    ui/index.js
    ui/<App>App.jsx
    specs/SPEC.md       (filled from the standard template)
    specs/APP_PACKAGES.md   (copy of the platform's canonical APP_PACKAGES.md)
    README.md
    LICENSE
    .gitignore
    pyproject.toml
    tests/test_smoke.py

Usage:
    python scripts/new_app.py recipes
    python scripts/new_app.py my-cool-feature --description "Tracks my cool feature"

Placeholder — full implementation lands in a later chunk.
"""

import sys


def main() -> int:
    print("scripts/new_app.py — placeholder. Full implementation in a later chunk.")
    print("For now, copy from an existing skipperbot-app-* repo and edit by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
