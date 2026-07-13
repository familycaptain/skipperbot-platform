"""Agentic app — the VOICE side of #109.

When a needs_attention agentic task finishes, handle_agentic raises an owed
event (domain 'agentic'). The attention system routes it here: this voice skill
decides whether and how to tell the family, and delivers in Skipper's one voice
(mirrors the goals milestone runner). Silence is a valid outcome.
"""
import logging

logger = logging.getLogger("apps.agentic.handlers")


async def _agentic_voice_runner(event: dict) -> dict:
    """Voice runner for a needs_attention agentic-task result."""
    import asyncio
    import json as _json
    import agent_loop
    from data_layer.users import get_primary_user
    from app_platform.consciousness import send_message

    payload = event.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except Exception:
            payload = {}

    result_text = event.get("content") or ""
    if not result_text.strip():
        return {"summary": "no agentic result to deliver"}
    primary = ((await asyncio.to_thread(get_primary_user)) or "").strip().lower()
    if not primary:
        return {"summary": "no primary user"}

    sent = []

    async def _dispatch(name: str, args: dict) -> str:
        if name != "send_message":
            return "unknown tool"
        if sent:
            return "already delivered"
        row = await asyncio.to_thread(
            lambda: send_message(who_to=primary, content=args.get("message") or "",
                                 domain="agentic",
                                 payload={"agentic_event": event.get("id")}))
        sent.append(row["id"])
        return f"sent ({row['id']})"

    tool = {"type": "function", "function": {
        "name": "send_message",
        "description": f"Tell {primary} the result of the scheduled task, briefly and "
                       "self-contained (they didn't see it run).",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string", "description": "What to tell them."},
        }, "required": ["message"]},
    }}

    await agent_loop.run(
        messages=[
            {"role": "system", "content": (
                "A scheduled task you run for the household just finished and its "
                "result is set to be shared. Relay it to the primary user in your "
                "own voice — brief, warm, self-contained (they didn't watch it "
                "run). If the result is genuinely empty or not worth a ping, you "
                "may stay silent by not calling send_message.")},
            {"role": "user", "content": f"Task result:\n{result_text}"},
        ],
        tools=[tool], tier="fast", max_turns=2, max_tool_calls=1,
        tool_dispatch=_dispatch,
    )
    return {"summary": f"agentic result {'delivered' if sent else 'held (not worth a ping)'}"}


try:
    from app_platform.skills import register_skill
    register_skill("agentic", _agentic_voice_runner, layer="voice",
                   description="Delivers a scheduled agentic task's result in Skipper's voice")
except Exception:
    logger.warning("AGENTIC: voice skill registration unavailable", exc_info=True)
