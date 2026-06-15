"""ClaudeSDKBackend — run an Evolve agent turn through the **claude-agent-sdk** (EVOLVE.md §6).

This is the SDK-native replacement for the hand-rolled `ToolUseBackend`. One `run()` is one
agent turn: it drives a `ClaudeSDKClient` with the agent's composed system prompt, the real
Claude Code tools (Read/Grep/Glob/Bash, +Edit/Write when writes are allowed), and
`output_format` for the structured `emit` — then maps the result back to our `AgentResult`.

Why the SDK (vs our old loop):
  - **Shared session + prompt caching** — Stage 2 runs a whole work item in ONE session
    (resume/fork), so each agent reads the accumulated conversation at ~0.1x instead of
    re-scanning the codebase from scratch. (This backend is the single-turn building block.)
  - **Accurate cost** — `ResultMessage.total_cost_usd` is the actual billed cost incl. cache
    pricing, replacing our over-estimating `estimate_cost`.
  - **Real tools** — Read/Edit/Glob/Grep/Bash, not a 4-tool sandbox.
  - **Streaming** — `hooks` + the message stream feed the live mission-control view.

The `claude_agent_sdk` import is LAZY so this module imports fine on machines without the SDK
(dev-mint, CI); the SDK only needs to be present where agents actually run (box 1 / box 2).
"""
from __future__ import annotations

import asyncio

from apps.evolve.agents.base import AgentResult
from apps.evolve.agents.runner import render_input

# Read-only tool set for grounding / spec / review agents; writers also get Edit/Write.
_READ_TOOLS = ["Read", "Grep", "Glob", "Bash"]
_WRITE_TOOLS = ["Edit", "Write"]


def _tool_label(name: str, tool_input: dict) -> str:
    """One-line label for a tool call — what scrolls in the live activity log."""
    ti = tool_input or {}
    if name == "Bash":
        return f"$ {ti.get('command', '')}"[:300]
    if name in ("Read", "Edit", "Write"):
        return f"{name.lower()} {ti.get('file_path', ti.get('path', ''))}"
    if name in ("Grep", "Glob"):
        return f"{name.lower()} {ti.get('pattern', '')}"
    return name


class ClaudeSDKBackend:
    """Conforms to the Runner's Backend protocol: run(spec, payload, context, model, system)."""

    def __init__(self, *, repo_root: str = ".", allow_writes: bool = False,
                 max_turns: int = 40, max_budget_usd: float | None = None,
                 permission_mode: str = "bypassPermissions"):
        self.repo_root = repo_root
        self.allow_writes = allow_writes
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.permission_mode = permission_mode   # box 1/2 are the agents' machines
        self.on_tool = None   # optional callable(kind, message): live per-tool activity (set by Runner)

    def run(self, spec, payload: dict, context: dict | None, model: str,
            system: str = "") -> AgentResult:
        """Backend-protocol entrypoint — a standalone single-turn run (no shared session)."""
        return self.run_turn(spec, payload, context, model, system)

    def run_turn(self, spec, payload: dict, context: dict | None, model: str,
                 system: str = "", *, role_prompt: str | None = None,
                 resume: str | None = None, fork: bool = False) -> AgentResult:
        """One agent turn. `resume` continues a prior session (shared, cached conversation);
        `fork` branches it first (for adversarial critics — full context, independent branch).
        In a shared session, pass a FROZEN `system` (so the cached prefix survives) and the
        per-agent role as `role_prompt` (prepended to the user turn) — never vary `system`
        per turn or you invalidate the conversation cache. Returns AgentResult with `session_id`."""
        try:
            return asyncio.run(self._run(spec, payload, context, model, system, role_prompt, resume, fork))
        except Exception as e:  # surface, never crash the walk
            return AgentResult(spec.name, ok=False, error=f"{type(e).__name__}: {e}", model=model,
                               session_id=resume)

    async def _run(self, spec, payload, context, model, system, role_prompt, resume, fork) -> AgentResult:
        from claude_agent_sdk import (ClaudeSDKClient, ClaudeAgentOptions, HookMatcher,
                                      AssistantMessage, ResultMessage, ToolUseBlock, TextBlock,
                                      fork_session)

        if fork and resume:
            resume = fork_session(resume).session_id   # branch off the shared session, don't pollute it

        sink = self.on_tool
        tools = list(_READ_TOOLS) + (list(_WRITE_TOOLS) if self.allow_writes else [])

        async def pre_tool(input_data, tool_use_id, ctx):
            if sink:
                try:
                    sink("tool", _tool_label(input_data.get("tool_name", ""),
                                             input_data.get("tool_input") or {}))
                except Exception:
                    pass
            return {}

        opts = ClaudeAgentOptions(
            model=model,
            system_prompt=system or spec.resolved_prompt(),   # our role prompt REPLACES the preset (lean boot)
            allowed_tools=tools,
            permission_mode=self.permission_mode,
            setting_sources=[],                               # don't load CLAUDE.md / project settings
            cwd=self.repo_root,
            max_turns=self.max_turns,
            max_budget_usd=self.max_budget_usd,
            output_format={"type": "json_schema", "schema": spec.output_schema},
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool])]} if sink else None,
            resume=resume,
        )

        out = None
        cost = 0.0
        in_tok = out_tok = 0
        err = None
        sid = resume
        transcript: list[str] = []
        user = render_input(payload, context)
        if role_prompt:                       # per-agent role goes in the USER turn (system stays frozen → cache survives)
            user = role_prompt + "\n\n" + user
        async with ClaudeSDKClient(options=opts) as client:
            await client.query(user)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, ToolUseBlock):
                            # tool calls stream via the PreToolUse hook (real-time); transcript only here
                            transcript.append(_tool_label(b.name, b.input))
                        elif isinstance(b, TextBlock) and getattr(b, "text", "").strip():
                            # the agent's own narration ("now I'll check…") — stream it so the lane
                            # shows the reasoning, not just the tool calls. (Hook covers only tools.)
                            txt = b.text.strip()
                            transcript.append(txt)
                            if sink:
                                try:
                                    sink("text", txt[:600])
                                except Exception:
                                    pass
                elif isinstance(msg, ResultMessage):
                    out = msg.structured_output
                    cost = msg.total_cost_usd or 0.0
                    sid = msg.session_id or sid
                    u = msg.usage or {}
                    in_tok = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                              + u.get("cache_creation_input_tokens", 0))
                    out_tok = u.get("output_tokens", 0)
                    if msg.is_error:
                        err = (msg.errors or ["agent run errored"])[0]

        ok = out is not None and err is None
        return AgentResult(spec.name, ok=ok, output=out, model=model,
                           input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
                           raw_text="\n".join(transcript), session_id=sid,
                           error=err if not ok and err else (None if ok else "no structured output"))
