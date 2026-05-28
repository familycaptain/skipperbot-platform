"""Schedules — REST API router.

Mounted by the platform loader at ``/api/apps/schedules/``.

**Sub-chunk 8a:** scaffold. The existing REST endpoints for schedules
live in ``agent.py`` and will move here in a follow-up extraction
sub-chunk (paired with live validation), mirroring every other
packaged app's deferred extraction.
"""

from fastapi import APIRouter

router = APIRouter()
