"""Arcade — REST API (high-score board). Mounted at /api/apps/arcade."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from pydantic import BaseModel

from .data import (
    save_score,
    top_scores,
    VALID_GAMES,
    get_solitaire_save,
    set_solitaire_save,
    clear_solitaire_save,
)

router = APIRouter()


class ScoreIn(BaseModel):
    game: str
    player: str = ""
    score: int = 0


class SolitaireSaveIn(BaseModel):
    player: str = ""
    state: dict


@router.get("/scores")
async def api_top_scores(game: str = Query("", description="game id, blank = all"),
                         limit: int = Query(10, ge=1, le=100)):
    rows = await asyncio.to_thread(top_scores, game, limit)
    return {"scores": rows}


@router.post("/scores")
async def api_save_score(body: ScoreIn):
    if body.game not in VALID_GAMES:
        return {"ok": False, "error": f"unknown game '{body.game}'"}
    rec = await asyncio.to_thread(save_score, body.game, body.player, body.score)
    return {"ok": True, "score": rec}


# --- Solitaire save/restore (one in-progress game per user) ------------------

@router.get("/solitaire/save")
async def api_get_solitaire_save(player: str = Query("", description="canonical user name")):
    state = await asyncio.to_thread(get_solitaire_save, player)
    return {"state": state}


@router.put("/solitaire/save")
async def api_put_solitaire_save(body: SolitaireSaveIn):
    if not (body.player or "").strip():
        return {"ok": False, "error": "player required"}
    await asyncio.to_thread(set_solitaire_save, body.player, body.state)
    return {"ok": True}


@router.delete("/solitaire/save")
async def api_delete_solitaire_save(player: str = Query("", description="canonical user name")):
    await asyncio.to_thread(clear_solitaire_save, player)
    return {"ok": True}
