"""Weather app — REST API (forecast dashboard data). Mounted at /api/apps/weather."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from .data import weather_summary, nws_alerts

router = APIRouter()


@router.get("/summary")
async def api_summary(
    location: str = Query("", description="Place name or postal,country; blank uses the configured home location"),
    hours: int = Query(12, ge=1, le=48),
    days: int = Query(10, ge=1, le=16),
):
    """Current conditions + hourly + daily for the dashboard (one round-trip).

    The resolved place is returned by lat/lon (place.display_label, lat, lon,
    country_code) — there is no ZIP in the contract.
    """
    return await asyncio.to_thread(weather_summary, location, hours, days)


@router.get("/alerts")
async def api_alerts(location: str = Query("", description="Place name or postal,country; blank uses the configured home location")):
    """Active NWS severe-weather alerts near the location, as GeoJSON (for the map).

    NWS alerts are US-only; a non-US location returns an explicit message.
    """
    return await asyncio.to_thread(nws_alerts, location)
