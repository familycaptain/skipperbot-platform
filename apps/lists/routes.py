"""Lists — REST API router.

Mounted by the platform loader at ``/api/apps/lists/``.

**Sub-chunk 4a:** scaffold. The existing REST endpoints for lists live
in ``agent.py`` under ``/api/apps/lists/...`` and will move here in a
follow-up extraction sub-chunk (paired with live validation), mirroring
the goals app's deferred extraction.
"""

from fastapi import APIRouter

router = APIRouter()
