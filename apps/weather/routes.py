"""Weather app — REST API (forecast dashboard data). Mounted at /api/apps/weather."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from .data import weather_summary

router = APIRouter()


@router.get("/summary")
async def api_summary(
    zip: str = Query("", description="US ZIP code; blank uses the configured default"),
    hours: int = Query(12, ge=1, le=48),
    days: int = Query(10, ge=1, le=16),
):
    """Current conditions + hourly + daily for the dashboard (one round-trip)."""
    return await asyncio.to_thread(weather_summary, zip, hours, days)
