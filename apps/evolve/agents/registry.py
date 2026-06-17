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
# Every reasoning agent leads with `summary`: a plain-language headline a human reads
# first (the Runner's composed_system mandates its content). Surfaced as the agent's panel.
TRIAGE_OUT = _obj({
    "summary": _STR,
    "disposition": {"type": "string", "enum": ["proceed", "duplicate", "malicious", "invalid"]},
                                                 # anything but 'proceed' is REJECTED at triage — never passed downstream
    "kind": {"type": "string", "enum": ["bug", "feature"]},  # drives routing (bug->spec, feature->vision)
    "spec_status": {"type": "string",
                    "enum": ["violates-spec", "no-spec", "conflicts-spec", "unclear"]},
    "conflicting_spec": _STR,                     # spec id when spec_status == conflicts-spec, else ""
    "duplicate_of": _STR,                         # "" if none
    "touches_cfs": _arr(_STR),                    # candidate C/F/S ids
    "belongs_to": _STR,                           # where the FIX lives: "platform" (this repo) or an
                                                  # external app-package name Evolve here can't build
    "rationale": _STR,
}, ["summary", "kind", "rationale"])               # spec_status + belongs_to prompt-mandated; optional in schema

VISION_OUT = _obj({
    "summary": _STR,
    "verdict": {"type": "string", "enum": ["fits", "off-vision", "needs-charter-change"]},
    "rationale": _STR,
}, ["summary", "verdict", "rationale"])

SPEC_AUTHOR_OUT = _obj({
    "summary": _STR,
    "capability": _STR, "feature": _STR, "spec_id": _STR,
    "title": _STR, "behavior": _STR,
    "implements": _arr(_STR),
    "tests": _arr(_obj({"type": _STR, "path": _STR, "rubric": _STR}, ["type"])),
    "notes": _STR,
}, ["summary", "spec_id", "behavior"])

SPEC_AUDIT_OUT = _obj({
    "summary": _STR,
    "sound": _BOOL,
    "findings": _arr(_obj({
        "category": {"type": "string",
                     "enum": ["cardinality", "missing-state", "ambiguous-resolution",
                              "untestable", "unstated-precondition", "other"]},
        "detail": _STR,
        "severity": {"type": "string", "enum": ["low", "med", "high"]},
    }, ["category", "detail", "severity"])),
}, ["summary", "sound", "findings"])

INTEROP_OUT = _obj({
    "summary": _STR,
    "conflicts": _arr(_obj({"with_spec": _STR, "kind": _STR, "detail": _STR},
                           ["with_spec", "detail"])),
}, ["summary", "conflicts"])

REVIEW_OUT = _obj({
    "summary": _STR,
    "concerns": _arr(_obj({"severity": {"type": "string", "enum": ["low", "med", "high"]},
                           "detail": _STR}, ["severity", "detail"])),
    "approve": _BOOL,
}, ["summary", "approve", "concerns"])

PRIORITIZE_OUT = _obj({
    "summary": _STR,
    "score": {"type": "number"},
    "decision": {"type": "string", "enum": ["surface", "park"]},
    "rationale": _STR,
}, ["summary", "score", "decision", "rationale"])

DESIGN_OUT = _obj({
    "summary": _STR,
    "approach": _STR,                  # how it should work, system-level — the headline design decision
    "key_decisions": _arr(_STR),       # decisions it MADE (grounded in the real code it read)
    "decisions_needed": _arr(_obj({    # genuine forks for the HUMAN — each with a recommendation
        "question": _STR, "options": _arr(_STR), "recommendation": _STR}, ["question", "recommendation"])),
    "in_scope": _arr(_STR),
    "out_of_scope": _arr(_STR),
    "nonfunctional": _arr(_STR),       # which operator principles apply + how this honors them
    "sizing": {"type": "string", "enum": ["one-spec", "needs-tree"]},   # decomposition signal (#30)
    "spec_tree": _arr(_obj({           # when needs-tree: the leaf specs the Lead should author
        "spec_id": _STR, "title": _STR, "summary": _STR}, ["spec_id", "title"])),
}, ["summary", "approach", "key_decisions", "sizing"])

# Shared codebase grounding — scanned ONCE per work item, then handed to every downstream
# agent so they don't each re-read the code from scratch (the re-scan tax).
GROUNDING_OUT = _obj({
    "summary": _STR,                       # what this area of the code does + how the change fits
    "relevant_files": _arr(_obj({          # the files that matter for this work item
        "path": _STR, "role": _STR}, ["path", "role"])),
    "key_symbols": _arr(_obj({             # functions/classes/routes the change will touch or use
        "name": _STR, "file": _STR, "role": _STR}, ["name", "role"])),
    "excerpts": _arr(_obj({                # crucial snippets so downstream agents needn't re-open files
        "path": _STR, "snippet": _STR}, ["path", "snippet"])),
    "conventions": _arr(_STR),             # patterns/idioms to follow (so the change fits in)
    "entry_points": _arr(_STR),            # where behavior is wired (routes, tools, UI mount points)
}, ["summary", "relevant_files"])

LEAD_OUT = _obj({
    "summary": _STR,
    "verdict": {"type": "string", "enum": ["accept", "revise", "escalate"]},   # per-round arbitration
    "recommendation": _obj({
        "action": {"type": "string", "enum": ["approve", "change", "reject"]},
        "current": _STR,   # how the affected behavior works TODAY (the status quo / problem)
        "after": _STR,     # how it will work ONCE this ships — what the operator is approving
        "why": _STR,
    }, ["action", "why"]),                                                       # final Gate-1 recommendation
    "note": _STR,
}, ["summary"])

PACKET_OUT = _obj({
    "summary": _STR, "risk": {"type": "string", "enum": ["low", "med", "high"]},
    "test_summary": _STR,
    "recommendation": {"type": "string", "enum": ["approve", "reject", "change"]},
    "recommendation_why": _STR,
}, ["summary", "risk", "recommendation", "recommendation_why"])

# --- code-acting agents (run on the Agent SDK tool-use path; execute skills) ---
IMPLEMENT_OUT = _obj({
    "summary": _STR, "files_changed": _arr(_STR), "ok": _BOOL,
}, ["summary", "ok"])

TEST_AUTHOR_OUT = _obj({
    "tests_written": _arr(_STR), "summary": _STR,
}, ["tests_written", "summary"])

VALIDATE_OUT = _obj({
    "summary": _STR, "passed": _BOOL, "failures": _arr(_STR), "notes": _STR,
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
        charter_keys=["thesis", "surfaces", "principles"],
        requires_tools=True, skills=["explore-code"], max_tokens=4096),   # reads real code first
    "spec-audit": AgentSpec(
        "spec-audit", "Critique a single spec for gaps/holes/naive assumptions.",
        SPEC_AUDIT_OUT, prompt_file="spec-audit.md", tier="deep",
        charter_keys=["surfaces"],
        requires_tools=True, skills=["explore-code"], max_tokens=4096),   # checks spec vs real code
    "interop": AgentSpec(
        "interop", "Detect spec-vs-spec conflicts (is the desired state satisfiable?).",
        INTEROP_OUT, prompt_file="interop.md", tier="deep"),
    "security": AgentSpec(
        "security", "Review a change for vulnerabilities + supply-chain risk.",
        REVIEW_OUT, prompt_file="security.md", tier="deep", charter_keys=["non-goals"]),
    "architecture": AgentSpec(
        "architecture", "Review system fit: boundaries, the one-directional dep rule.",
        REVIEW_OUT, prompt_file="architecture.md", tier="deep", charter_keys=["is", "surfaces", "principles"]),
    "ux": AgentSpec(
        "ux", "Review UX/UI quality + cross-app consistency.",
        REVIEW_OUT, prompt_file="ux.md", tier="deep", charter_keys=["surfaces"]),
    "prioritize": AgentSpec(
        "prioritize", "Score a proposal onto one ranked queue; surface or park.",
        PRIORITIZE_OUT, prompt_file="prioritize.md", tier="deep",
        charter_keys=["thesis"], max_tokens=3072),   # headroom: summary + score + rationale must all fit
    "grounding": AgentSpec(
        "grounding", "Scan the codebase ONCE and produce a reusable digest for the whole spec team.",
        GROUNDING_OUT, prompt_file="grounding.md", tier="deep",
        requires_tools=True, skills=["explore-code"], max_tokens=4096),   # the one cold scan per work item
    "design": AgentSpec(
        "design", "Set the system-level approach (how it should work) before the spec is written.",
        DESIGN_OUT, prompt_file="design.md", tier="deep",
        charter_keys=["scope", "surfaces", "principles"],
        requires_tools=True, skills=["explore-code"], max_tokens=4096),   # reads real code before deciding
    "lead": AgentSpec(
        "lead", "Engineering lead: arbitrate the spec team + own the Gate-1 proposal and recommendation.",
        LEAD_OUT, prompt_file="lead.md", tier="deep",
        charter_keys=["thesis", "scope", "principles"]),
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
        charter_keys=["surfaces", "principles"], skills=["cfs-validate", "run-evolve-tests"], max_tokens=8192),
    "test-author": AgentSpec(
        "test-author", "Write/update a spec's bound acceptance tests.",
        TEST_AUTHOR_OUT, prompt_file="test-author.md", tier="deep", requires_tools=True,
        skills=["run-evolve-tests"], max_tokens=8192),
    "validate": AgentSpec(
        "validate", "Run a spec's bound tests on box 2 and judge the result.",
        VALIDATE_OUT, prompt_file="validate.md", tier="deep", requires_tools=True,
        skills=["run-evolve-tests"]),
}


def get(name: str) -> AgentSpec | None:
    return ROSTER.get(name)
