"""
onboarding.py — CLI onboarding wizard.

For users running headless or anyone who prefers a terminal walkthrough
over the web wizard. Interactive prompts that:

- Test DB connectivity.
- Test OPENAI_API_KEY against /v1/models.
- Insert the primary user into public.users.
- Write any missing values into .env.
- Print URLs for the web UI and next steps.

The web wizard (web/src/pages/Onboarding.jsx) covers the same ground for
users who prefer a browser; the two paths share the same /api/onboarding/*
endpoints.

Usage:
    python scripts/onboarding.py

Placeholder — full implementation lands in Chunk 2.
"""

import sys


def main() -> int:
    print("scripts/onboarding.py — placeholder. Full implementation in Chunk 2.")
    print("For now, use the web wizard at http://localhost:8000/onboarding")
    print("after the agent is running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
