"""Goals — REST API router.

FastAPI router mounted by the platform loader at ``/api/apps/goals/``.

**Status:** scaffold + pending extraction.

The 16 goals REST endpoints currently live in ``agent.py`` at
``/api/apps/goals/...``. They already use ``apps.goals.data`` and
``apps.goals.store`` (Chunk 3e's cross-platform refactor wired those
imports correctly). Functional today; structurally they belong here.

The extraction is mechanical — each route is independently translatable::

    # in agent.py
    @app.get("/api/apps/goals/summary")
    async def goals_summary():
        ...

    # becomes, in this file:
    @router.get("/summary")
    async def goals_summary():
        ...

But moving 16 routes blindly is just shuffling. A dedicated follow-up
sub-chunk will pair the move with live agent-up validation: stand up
the platform, hit each endpoint with curl, confirm shape + behavior,
then remove from agent.py one at a time.

## Endpoints to extract (16, all currently in agent.py)

| Method | Path |
|---|---|
| GET    | /api/apps/goals/summary |
| GET    | /api/apps/goals/tasks/{task_id} |
| GET    | /api/apps/goals/trello/board-labels/{board_name} |
| POST   | /api/apps/goals/trello/card-labels/{card_id}/add |
| POST   | /api/apps/goals/trello/card-labels/{card_id}/remove |
| GET    | /api/apps/goals/projects/{project_id} |
| GET    | /api/apps/goals/search |
| GET    | /api/apps/goals/{goal_id} |
| PATCH  | /api/apps/goals/entities/{entity_id} |
| POST   | /api/apps/goals |
| POST   | /api/apps/goals/projects |
| POST   | /api/apps/goals/tasks |
| POST   | /api/apps/goals/tasks/reorder |
| PUT    | /api/apps/goals/entities/{entity_id}/notes |
| DELETE | /api/apps/goals/entities/{entity_id} |
| GET    | /api/apps/goals/my-tasks/{user_id} |

The loader auto-mounts this router (when populated) at the same
``/api/apps/goals/`` prefix — so URL paths don't change post-extraction.
The Goals + Tasks desktop apps continue calling the same URLs.
"""

from fastapi import APIRouter

router = APIRouter()


# Endpoints land here in the follow-up extraction sub-chunk.
