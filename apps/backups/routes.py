"""Backups — FastAPI routes stub.

The backups REST endpoints live under ``/api/apps/backups/*``
inside ``agent.py`` so the existing ``BackupsApp.jsx`` keeps working
without a URL migration. This stub exists so the loader's
``has_routes`` check doesn't trip — if/when those handlers move
fully into this app, the agent.py block moves here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
