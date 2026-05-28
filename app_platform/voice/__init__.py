"""Platform Voice Handlers
============================
Server-side voice support for the ``skipperbot-voice`` companion service.

After voice extraction (Phase 1e), the actual wake-word + audio I/O code
runs in a separate ``skipperbot-voice`` process. This subpackage holds
everything the *platform* needs to serve that process:

- ``session``  — OpenAI Realtime ephemeral token minting + in-memory session state.
- ``prompting`` — system prompt + tool schema construction (uses the
  app loader to discover installed apps' tools).
- ``tool_runtime`` — executes tool calls invoked over the voice REST API.
- ``chatlog`` — persists voice transcripts to chatlogs.

The platform exposes these to ``skipperbot-voice`` via REST endpoints
under ``/api/voice/*``. See ``specs/PLATFORM_SERVICES.md`` for the contract.
"""
