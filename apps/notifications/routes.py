"""Notifications — REST API router.

Mounted by the platform loader at ``/api/apps/notifications``.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from .data import get_notifications_for_user

router = APIRouter()


@router.get("")
async def list_notifications(recipient: str = "", limit: int = 50):
    """List notifications for a recipient, newest first.

    Backs the Notifications app UI.
    """
    notifications = await asyncio.to_thread(get_notifications_for_user, recipient, limit)
    return {"notifications": notifications}
