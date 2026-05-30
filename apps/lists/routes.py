"""Lists — REST API router. Mounted at /api/apps/lists.

Trello multi-account + multi-board configuration (creds encrypted at rest),
managed from the Lists app UI.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from . import trello_config as _tc

router = APIRouter()


# ---- Accounts ----

@router.get("/trello/accounts")
async def list_trello_accounts():
    return {"accounts": await asyncio.to_thread(_tc.list_accounts)}


class TrelloAccountIn(BaseModel):
    name: str
    api_key: str = ""      # blank = keep existing
    api_token: str = ""    # blank = keep existing


@router.post("/trello/accounts")
async def save_trello_account(body: TrelloAccountIn):
    if not body.name.strip():
        return {"ok": False, "error": "account name is required"}
    await asyncio.to_thread(_tc.save_account, body.name, body.api_key, body.api_token)
    return {"ok": True, "accounts": await asyncio.to_thread(_tc.list_accounts)}


@router.delete("/trello/accounts/{name}")
async def delete_trello_account(name: str):
    ok = await asyncio.to_thread(_tc.delete_account, name)
    return {"ok": ok}


# ---- Boards ----

@router.get("/trello/boards")
async def list_trello_boards():
    return {"boards": await asyncio.to_thread(_tc.list_boards)}


class TrelloBoardIn(BaseModel):
    name: str
    account: str
    board_id: str = ""
    default_list: str = ""


@router.post("/trello/boards")
async def save_trello_board(body: TrelloBoardIn):
    if not body.name.strip() or not body.account.strip():
        return {"ok": False, "error": "board name and account are required"}
    await asyncio.to_thread(_tc.save_board, body.name, body.account, body.board_id, body.default_list)
    return {"ok": True, "boards": await asyncio.to_thread(_tc.list_boards)}


@router.delete("/trello/boards/{name}")
async def delete_trello_board_route(name: str):
    ok = await asyncio.to_thread(_tc.delete_board, name)
    return {"ok": ok}
