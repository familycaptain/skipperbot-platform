"""Agent framework — base types (EVOLVE.md §6/§7).

A single-responsibility agent = a curated system prompt + a typed input + a typed
(JSON-schema) output. The runner (runner.py) executes a spec against a backend
(fake for tests, Anthropic for real). This module holds the dataclasses + a minimal
output-schema validator (so we don't depend on the `jsonschema` package).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# model tiers -> resolved at the runner; agents pick a tier, not a model id.
TIERS = ("fast", "smart", "deep")


@dataclass
class AgentSpec:
    """One agent: its job, its prompt, and the shape of what it must return."""
    name: str
    description: str
    output_schema: dict                       # JSON schema the result must satisfy
    system_prompt: str = ""                    # inline; or load via prompt_file
    prompt_file: str | None = None             # relative to apps/evolve/agents/prompts/
    tier: str = "smart"
    max_tokens: int = 2048
    max_cost_usd: float = 0.50                 # per-run guardrail (budget, §7)

    def resolved_prompt(self) -> str:
        if self.system_prompt:
            return self.system_prompt
        if self.prompt_file:
            path = os.path.join(os.path.dirname(__file__), "prompts", self.prompt_file)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read()
        return f"You are the {self.name} agent. {self.description}"


@dataclass
class AgentResult:
    agent: str
    ok: bool
    output: dict | None = None
    error: str | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw_text: str = ""
    schema_errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Minimal JSON-Schema validation (the subset our agent schemas use)
# --------------------------------------------------------------------------- #
def validate_against_schema(schema: dict, data) -> list[str]:
    """Validate `data` against a small JSON-schema subset: object/array, type,
    required, properties, enum, items. Returns a list of error strings ([] = ok)."""
    errs: list[str] = []

    def check(node_schema: dict, value, path: str):
        t = node_schema.get("type")
        if t == "object":
            if not isinstance(value, dict):
                errs.append(f"{path}: expected object, got {type(value).__name__}")
                return
            for req in node_schema.get("required", []):
                if req not in value:
                    errs.append(f"{path}: missing required '{req}'")
            props = node_schema.get("properties", {})
            for k, v in value.items():
                if k in props:
                    check(props[k], v, f"{path}.{k}")
        elif t == "array":
            if not isinstance(value, list):
                errs.append(f"{path}: expected array, got {type(value).__name__}")
                return
            item_schema = node_schema.get("items")
            if item_schema:
                for i, item in enumerate(value):
                    check(item_schema, item, f"{path}[{i}]")
        elif t == "string":
            if not isinstance(value, str):
                errs.append(f"{path}: expected string, got {type(value).__name__}")
        elif t == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                errs.append(f"{path}: expected integer")
        elif t == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errs.append(f"{path}: expected number")
        elif t == "boolean":
            if not isinstance(value, bool):
                errs.append(f"{path}: expected boolean")
        enum = node_schema.get("enum")
        if enum is not None and value not in enum:
            errs.append(f"{path}: '{value}' not in enum {enum}")

    check(schema, data, "$")
    return errs
