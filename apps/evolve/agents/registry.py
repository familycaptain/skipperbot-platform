"""The agent roster (EVOLVE.md §6) as typed AgentSpecs.

Each agent is single-responsibility: a curated system prompt (prompts/<name>.md) +
a JSON-schema output contract. The roster is data — add an agent by adding an entry
here + a prompt file; the runner + engine pick it up with no other change (the
"scales to any N agents" property, §6).
"""
from __future__ import annotations

from apps.evolve.agents.base import AgentSpec


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


# --------------------------------------------------------------------------- #
# Output schemas
# --------------------------------------------------------------------------- #
TRIAGE_OUT = _obj({
    "kind": {"type": "string", "enum": ["bug", "feature"]},
    "duplicate_of": _STR,                         # "" if none
    "touches_cfs": _arr(_STR),                    # candidate C/F/S ids
    "rationale": _STR,
}, ["kind", "rationale"])

VISION_OUT = _obj({
    "verdict": {"type": "string", "enum": ["fits", "off-vision", "needs-charter-change"]},
    "rationale": _STR,
}, ["verdict", "rationale"])

SPEC_AUTHOR_OUT = _obj({
    "capability": _STR, "feature": _STR, "spec_id": _STR,
    "title": _STR, "behavior": _STR,
    "implements": _arr(_STR),
    "tests": _arr(_obj({"type": _STR, "path": _STR, "rubric": _STR}, ["type"])),
    "notes": _STR,
}, ["spec_id", "behavior"])

SPEC_AUDIT_OUT = _obj({
    "sound": _BOOL,
    "findings": _arr(_obj({
        "category": {"type": "string",
                     "enum": ["cardinality", "missing-state", "ambiguous-resolution",
                              "untestable", "unstated-precondition", "other"]},
        "detail": _STR,
        "severity": {"type": "string", "enum": ["low", "med", "high"]},
    }, ["category", "detail", "severity"])),
}, ["sound", "findings"])

INTEROP_OUT = _obj({
    "conflicts": _arr(_obj({"with_spec": _STR, "kind": _STR, "detail": _STR},
                           ["with_spec", "detail"])),
}, ["conflicts"])

REVIEW_OUT = _obj({
    "concerns": _arr(_obj({"severity": {"type": "string", "enum": ["low", "med", "high"]},
                           "detail": _STR}, ["severity", "detail"])),
    "approve": _BOOL,
}, ["approve", "concerns"])

PRIORITIZE_OUT = _obj({
    "score": {"type": "number"},
    "decision": {"type": "string", "enum": ["surface", "park"]},
    "rationale": _STR,
}, ["score", "decision", "rationale"])

DESIGN_OUT = _obj({
    "proposals": _arr(_obj({"title": _STR, "capability": _STR, "need": _STR,
                            "rationale": _STR}, ["title", "need"])),
}, ["proposals"])

PACKET_OUT = _obj({
    "summary": _STR, "risk": {"type": "string", "enum": ["low", "med", "high"]},
    "test_summary": _STR,
}, ["summary", "risk"])

# --- code-acting agents (run on the Agent SDK tool-use path; execute skills) ---
IMPLEMENT_OUT = _obj({
    "summary": _STR, "files_changed": _arr(_STR), "ok": _BOOL,
}, ["summary", "ok"])

TEST_AUTHOR_OUT = _obj({
    "tests_written": _arr(_STR), "summary": _STR,
}, ["tests_written", "summary"])

VALIDATE_OUT = _obj({
    "passed": _BOOL, "failures": _arr(_STR), "notes": _STR,
}, ["passed"])


# --------------------------------------------------------------------------- #
# The roster
# --------------------------------------------------------------------------- #
# Model-tier policy (operator directive): reasoning + code-acting agents run on
# Opus 4.8 (`deep`) — thoughts/judgment/code need the strongest model. Haiku (`fast`)
# is reserved for small, discrete tasks only (triage classify, packet assembly). The
# `smart`/Sonnet tier stays defined but is currently unused.
ROSTER: dict[str, AgentSpec] = {
    "triage": AgentSpec(
        "triage", "Classify a work item (bug vs feature), dedup, link to C/F/S.",
        TRIAGE_OUT, prompt_file="triage.md", tier="fast"),
    "vision-fit": AgentSpec(
        "vision-fit", "Judge a feature against the charter + Capability scope.",
        VISION_OUT, prompt_file="vision-fit.md", tier="deep",
        charter_keys=["thesis", "non-goals", "scope"]),
    "spec-author": AgentSpec(
        "spec-author", "Turn accepted intent into a C/F/S record + bound tests.",
        SPEC_AUTHOR_OUT, prompt_file="spec-author.md", tier="deep",
        charter_keys=["thesis", "surfaces"]),
    "spec-audit": AgentSpec(
        "spec-audit", "Critique a single spec for gaps/holes/naive assumptions.",
        SPEC_AUDIT_OUT, prompt_file="spec-audit.md", tier="deep",
        charter_keys=["surfaces"]),
    "interop": AgentSpec(
        "interop", "Detect spec-vs-spec conflicts (is the desired state satisfiable?).",
        INTEROP_OUT, prompt_file="interop.md", tier="deep"),
    "security": AgentSpec(
        "security", "Review a change for vulnerabilities + supply-chain risk.",
        REVIEW_OUT, prompt_file="security.md", tier="deep", charter_keys=["non-goals"]),
    "architecture": AgentSpec(
        "architecture", "Review system fit: boundaries, the one-directional dep rule.",
        REVIEW_OUT, prompt_file="architecture.md", tier="deep", charter_keys=["is", "surfaces"]),
    "ux": AgentSpec(
        "ux", "Review UX/UI quality + cross-app consistency.",
        REVIEW_OUT, prompt_file="ux.md", tier="deep", charter_keys=["surfaces"]),
    "prioritize": AgentSpec(
        "prioritize", "Score a proposal onto one ranked queue; surface or park.",
        PRIORITIZE_OUT, prompt_file="prioritize.md", tier="deep",
        charter_keys=["thesis"]),
    "design": AgentSpec(
        "design", "Propose new Capabilities/Features grounded in charter + gaps.",
        DESIGN_OUT, prompt_file="design.md", tier="deep",
        charter_keys=["thesis", "scope", "surfaces", "non-goals"]),
    "code-audit": AgentSpec(
        "code-audit", "Read code for logic bugs, edge cases, security smells, dead code.",
        SPEC_AUDIT_OUT, prompt_file="code-audit.md", tier="deep", charter_keys=["non-goals"]),
    "review-packet": AgentSpec(
        "review-packet", "Assemble the pre-digested Gate-2 review packet.",
        PACKET_OUT, prompt_file="review-packet.md", tier="fast"),

    # --- code-acting agents: execute Claude Skills + tools on the Agent SDK path ---
    # (requires_tools=True => the Messages backend refuses them; they need the SDK
    #  backend, which is the documented next build. They carry skills today.)
    "implement": AgentSpec(
        "implement", "Write the code that converges the codebase to an approved spec.",
        IMPLEMENT_OUT, prompt_file="implement.md", tier="deep", requires_tools=True,
        charter_keys=["surfaces"], skills=["cfs-validate", "run-evolve-tests"]),
    "test-author": AgentSpec(
        "test-author", "Write/update a spec's bound acceptance tests.",
        TEST_AUTHOR_OUT, prompt_file="test-author.md", tier="deep", requires_tools=True,
        skills=["run-evolve-tests"]),
    "validate": AgentSpec(
        "validate", "Run a spec's bound tests on box 2 and judge the result.",
        VALIDATE_OUT, prompt_file="validate.md", tier="deep", requires_tools=True,
        skills=["run-evolve-tests"]),
}


def get(name: str) -> AgentSpec | None:
    return ROSTER.get(name)
