"""Reminders — REST API router.

Mounted by the platform loader at ``/api/apps/reminders/``.

**Sub-chunk 7a:** scaffold. The existing REST endpoints for reminders
live in ``agent.py`` and will move here in a follow-up extraction
sub-chunk (paired with live validation), mirroring the goals / lists /
todo / notifications apps' deferred extractions.
"""

from fastapi import APIRouter

router = APIRouter()
