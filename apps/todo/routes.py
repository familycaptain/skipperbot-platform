"""Todo — REST API router.

Mounted by the platform loader at ``/api/apps/todo/``.

**Sub-chunk 5a:** scaffold. The existing REST endpoints for todo live
in ``agent.py`` under ``/api/apps/todo/...`` and will move here in a
follow-up extraction sub-chunk (paired with live validation), mirroring
the goals + lists apps' deferred extractions.
"""

from fastapi import APIRouter

router = APIRouter()
