"""Agent runner — executes an AgentSpec against a backend (EVOLVE.md §6/§7).

Backends:
  FakeBackend      — deterministic, no network; used in tests + offline dev.
  AnthropicBackend — the real swarm->Claude path (Anthropic Messages API, forced-tool
                     structured output). Reports token usage + estimated cost.

The runner enforces per-run output caps (max_tokens), validates every result against
the agent's output schema, and tracks a cumulative cost budget (the §7 guardrail).
This is the "data plane": one bounded call per agent invocation.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Protocol

from apps.evolve.agents import charter
from apps.evolve.agents.base import AgentSpec, AgentResult, validate_against_schema

# Tier -> Anthropic model id. Evolve runs on Claude (separate from the platform's
# OpenAI assistant). Override via env EVOLVE_MODEL_FAST / _SMART / _DEEP.
MODEL_TIERS = {
    "fast": os.getenv("EVOLVE_MODEL_FAST", "claude-haiku-4-5-20251001"),
    "smart": os.getenv("EVOLVE_MODEL_SMART", "claude-sonnet-4-6"),
    "deep": os.getenv("EVOLVE_MODEL_DEEP", "claude-opus-4-8"),
}

# Approximate USD per 1M tokens (input, output). APPROXIMATE — adjust to billed rates.
PRICING = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
}


def estimate_cost(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = PRICING.get(model, (3.0, 15.0))
    return round(in_tok / 1e6 * pin + out_tok / 1e6 * pout, 6)


def render_input(payload: dict, context: dict | None) -> str:
    parts = ["Input:", json.dumps(payload, indent=2, default=str)]
    if context:
        parts += ["\nContext:", json.dumps(context, indent=2, default=str)]
    parts.append("\nReturn your result by calling the `emit` tool — nothing else.")
    return "\n".join(parts)


class Backend(Protocol):
    def run(self, spec: AgentSpec, payload: dict, context: dict | None, model: str,
            system: str) -> AgentResult: ...


# --------------------------------------------------------------------------- #
# Fake backend (tests / offline)
# --------------------------------------------------------------------------- #
class FakeBackend:
    """Deterministic backend. `responder` is either a dict {agent_name: output}
    or a callable (spec, payload, context) -> output dict."""

    def __init__(self, responder: dict | Callable):
        self.responder = responder
        self.calls: list[tuple[str, dict]] = []

    def run(self, spec: AgentSpec, payload: dict, context: dict | None, model: str,
            system: str = "") -> AgentResult:
        self.calls.append((spec.name, payload))
        if callable(self.responder):
            out = self.responder(spec, payload, context)
        else:
            out = self.responder.get(spec.name)
        if out is None:
            return AgentResult(spec.name, ok=False, error=f"no fake response for '{spec.name}'", model=model)
        return AgentResult(spec.name, ok=True, output=out, model=model,
                           input_tokens=0, output_tokens=0, cost_usd=0.0,
                           raw_text=json.dumps(out))


# --------------------------------------------------------------------------- #
# Anthropic backend (the real swarm -> Claude path)
# --------------------------------------------------------------------------- #
class AnthropicBackend:
    """Anthropic Messages API with forced-tool structured output. Lazily imports
    `anthropic` and reads ANTHROPIC_API_KEY, so importing this module never requires
    the SDK or a key."""

    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        if self._client is None:
            import anthropic                      # lazy
            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        return self._client

    def run(self, spec: AgentSpec, payload: dict, context: dict | None, model: str,
            system: str = "") -> AgentResult:
        if spec.requires_tools:
            return AgentResult(spec.name, ok=False, model=model,
                               error="requires the Agent SDK tool-use backend (executes "
                                     "skills/tools); the Messages backend can't run it. "
                                     "See .claude/skills/ + apps/evolve/README.md.")
        try:
            client = self._get_client()
            emit_tool = {"name": "emit",
                         "description": "Return the agent's structured result.",
                         "input_schema": spec.output_schema}
            msg = client.messages.create(
                model=model, max_tokens=spec.max_tokens,
                system=system or spec.resolved_prompt(),
                tools=[emit_tool], tool_choice={"type": "tool", "name": "emit"},
                messages=[{"role": "user", "content": render_input(payload, context)}])
            out = next((b.input for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
            cost = estimate_cost(model, msg.usage.input_tokens, msg.usage.output_tokens)
            return AgentResult(spec.name, ok=out is not None, output=out, model=model,
                               input_tokens=msg.usage.input_tokens,
                               output_tokens=msg.usage.output_tokens, cost_usd=cost,
                               raw_text=json.dumps(out) if out else "",
                               error=None if out is not None else "model returned no tool_use")
        except Exception as e:  # network/billing/validation — surface, don't crash the swarm
            return AgentResult(spec.name, ok=False, error=f"{type(e).__name__}: {e}", model=model)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
@dataclass
class Runner:
    backend: Backend
    registry: dict[str, AgentSpec]
    budget_usd: float | None = None            # cumulative cap across runs (None = unbounded)
    spent_usd: float = 0.0
    tiers: dict = field(default_factory=lambda: dict(MODEL_TIERS))
    charter_path: str = charter.DEFAULT_PATH   # source for per-agent charter grounding
    tool_backend: Backend | None = None        # for requires_tools agents (executes skills)
    ledger: object | None = None               # CostLedger: record every call (measure everything)
    monthly_limit_usd: float | None = None      # kill-switch: pause when month-to-date >= this

    def composed_system(self, spec: AgentSpec) -> str:
        """Role prompt + the curated charter sections this agent declares + the summary rule."""
        ground = charter.grounding(spec.charter_keys, self.charter_path)
        base = spec.resolved_prompt()
        summary_rule = (
            "\n\n# Always lead with a `summary`\n"
            "Your result includes a `summary`: 1-3 plain-language sentences a busy human reads "
            "FIRST — your bottom line, no jargon without a gloss. If you reframed the request, "
            "say so explicitly: what was asked vs. what is actually needed, and the key WHY "
            "(e.g. \"asked for city/state/zip; really needs a geocode to lat/lon because the "
            "weather API runs on coordinates\")."
        )
        return base + ("\n\n" + ground if ground else "") + summary_rule

    def run(self, agent_name: str, payload: dict, context: dict | None = None,
            instance_id: str | None = None) -> AgentResult:
        spec = self.registry.get(agent_name)
        if spec is None:
            return AgentResult(agent_name, ok=False, error=f"unknown agent '{agent_name}'")
        # monthly kill-switch: stop Evolve once month-to-date spend hits the cap
        if self.ledger is not None and self.monthly_limit_usd is not None:
            mtd = self.ledger.month_to_date()
            if mtd >= self.monthly_limit_usd:
                return AgentResult(agent_name, ok=False,
                                   error=f"Evolve paused: monthly budget reached "
                                         f"(${mtd:.2f} >= ${self.monthly_limit_usd:.2f})")
        if self.budget_usd is not None and self.spent_usd >= self.budget_usd:
            return AgentResult(agent_name, ok=False,
                               error=f"cycle budget exhausted (${self.spent_usd:.4f} >= ${self.budget_usd:.2f})")
        model = self.tiers.get(spec.tier, self.tiers["smart"])
        backend = self.tool_backend if (spec.requires_tools and self.tool_backend) else self.backend
        res = backend.run(spec, payload, context, model, self.composed_system(spec))
        self.spent_usd += res.cost_usd
        if self.ledger is not None:
            self.ledger.record_result(res, instance_id=instance_id)
        # validate the structured output against the agent's schema
        if res.ok and res.output is not None:
            res.schema_errors = validate_against_schema(spec.output_schema, res.output)
            if res.schema_errors:
                res.ok = False
                res.error = "output failed schema: " + "; ".join(res.schema_errors[:4])
        return res

    @property
    def remaining_usd(self) -> float | None:
        return None if self.budget_usd is None else max(0.0, self.budget_usd - self.spent_usd)
