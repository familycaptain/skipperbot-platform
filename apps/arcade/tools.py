"""Arcade — agent tools (read-only high-score lookups)."""

from __future__ import annotations

import asyncio


async def get_arcade_high_scores(game: str = "", limit: str = "10") -> str:
    """Show the arcade high-score leaderboard.

    Args:
        game: Optional game id to filter by ("wardenfall", "aeldrift",
              or "spinhazard"). Leave blank for the overall board.
        limit: Max rows to return (default "10").

    Returns:
        A formatted leaderboard, or a note that no scores exist yet.
    """
    from .data import top_scores
    try:
        n = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        n = 10
    rows = await asyncio.to_thread(top_scores, game.strip().lower(), n)
    if not rows:
        return "No arcade scores recorded yet — go play a game!"
    lines = [f"🎮 Arcade high scores{f' — {game}' if game else ''}:"]
    for i, r in enumerate(rows, 1):
        who = r["player"] or "anonymous"
        lines.append(f"{i}. {r['score']} — {who} ({r['game']})")
    return "\n".join(lines)
