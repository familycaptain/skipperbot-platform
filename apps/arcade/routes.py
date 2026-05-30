"""Arcade — REST API (high-score board). Mounted at /api/apps/arcade."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from pydantic import BaseModel

from .data import save_score, top_scores, VALID_GAMES

router = APIRouter()


class ScoreIn(BaseModel):
    game: str
    player: str = ""
    score: int = 0


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
