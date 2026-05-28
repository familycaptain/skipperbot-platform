"""Notifications — REST API router.

Mounted by the platform loader at ``/api/apps/notifications/``.

**Sub-chunk 6a:** scaffold. The existing REST endpoints for
notifications live in ``agent.py`` and will move here in a follow-up
extraction sub-chunk (paired with live validation), mirroring the
goals / lists / todo apps' deferred extractions.
"""

from fastapi import APIRouter

router = APIRouter()
