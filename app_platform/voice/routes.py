"""Voice REST Endpoints
========================
Server-side REST surface that the ``skipperbot-voice`` companion service
calls into.

**Phase 1e status:** placeholder. The actual `/api/voice/*` routes are
currently defined directly in ``agent.py`` because voice was co-located
with the agent process before the extraction. Phase 1e moves them here
and switches the wire format to the contract documented below.

Once Phase 1e is done, ``agent.py`` will do::

    from app_platform.voice.routes import router as voice_router
    app.include_router(voice_router, prefix="/api/voice")

and the in-process voice routes in ``agent.py`` get deleted.

REST contract (Phase 1e target):

| Endpoint | Body | Returns |
|----------|------|---------|
| ``POST /api/voice/session_start`` | ``{user_id, device_info?}`` | ``{ephemeral_token, model, voice, initial_tools, initial_instructions, session_id}`` |
| ``POST /api/voice/switch_app``    | ``{session_id, app_name}``  | ``{tools, instructions, app}`` |
| ``POST /api/voice/tool_call``     | ``{session_id, call_id, tool_name, arguments}`` | ``{events}`` |
| ``POST /api/voice/session_end``   | ``{session_id}``            | ``{ok}`` |

Every call requires ``Authorization: Bearer ${SKIPPERBOT_TOKEN}`` where
the token was issued by ``python scripts/service_token.py create voice``.

See ``specs/PLATFORM_SERVICES.md`` and ``specs/CAPABILITIES.md`` for the
broader contract context.
"""

# Placeholder — Phase 1e implementation lands here.
