"""Prioritize — FastAPI routes stub.

The prioritize REST endpoints live under ``/api/apps/prioritize/*``
inside ``agent.py`` so the existing ``PrioritizeApp.jsx`` keeps
working without a URL migration. This stub exists so the loader's
``has_routes`` check doesn't trip — if/when those handlers move
fully into this app, the agent.py block moves here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
