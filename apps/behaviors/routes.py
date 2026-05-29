"""Behaviors — FastAPI routes.

The behaviors REST endpoints live under the ``/api/behaviors`` prefix
inside ``agent.py`` so the existing ``BehaviorsApp.jsx`` keeps
working without a URL migration. This stub exists so the loader's
``has_routes`` check doesn't trip and so the per-app conventions stay
consistent — if/when the platform router gains a way to mount custom
prefixes per app, the agent.py block moves here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
