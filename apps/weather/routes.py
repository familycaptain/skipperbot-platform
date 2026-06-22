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
    lat: float | None = Query(None, description="Refresh by stored latitude (skips geocoding when lat+lon given)"),
    lon: float | None = Query(None, description="Refresh by stored longitude (skips geocoding when lat+lon given)"),
    label: str = Query("", description="Display label to show for a coordinate refresh"),
    cc: str = Query("", description="ISO country code for a coordinate refresh"),
):
    """Current conditions + hourly + daily for the dashboard (one round-trip).

    The resolved place is returned by lat/lon (place.display_label, lat, lon,
    country_code) — there is no ZIP in the contract. When lat+lon are supplied
    (refreshing a location the UI already resolved), the forecast is fetched by
    those coordinates with NO geocoding.
    """
    return await asyncio.to_thread(weather_summary, location, hours, days, lat, lon, label, cc)


@router.get("/alerts")
async def api_alerts(
    location: str = Query("", description="Place name or postal,country; blank uses the configured home location"),
    lat: float | None = Query(None, description="Refresh by stored latitude (skips geocoding when lat+lon given)"),
    lon: float | None = Query(None, description="Refresh by stored longitude (skips geocoding when lat+lon given)"),
    cc: str = Query("", description="ISO country code for the US-only alerts gate on a coordinate refresh"),
):
    """Active NWS severe-weather alerts near the location, as GeoJSON (for the map).

    NWS alerts are US-only; a non-US location returns an explicit message. When
    lat+lon are supplied (the Radar map already holds the coords), alerts are
    fetched by those coordinates with NO geocoding.
    """
    return await asyncio.to_thread(nws_alerts, location, lat, lon, cc)
