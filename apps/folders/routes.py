"""Folders — REST API router.

Mounted by the platform loader at ``/api/apps/folders/``.

**Sub-chunk 11a:** scaffold. The existing REST endpoints for folders
live in ``agent.py`` and will move here in a follow-up extraction
sub-chunk (paired with live validation).
"""

from fastapi import APIRouter

router = APIRouter()
