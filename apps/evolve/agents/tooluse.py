"""Tool-use backend — the Agent SDK path for code-acting agents (EVOLVE.md §6/§7).

Reasoning agents (Messages backend) produce structured output in one shot. Code-acting
agents (implement/test-author/validate) need to *do* things: run commands, read files,
execute their Claude Skills. This backend runs the agentic loop — Claude requests a
tool, we execute it, feed the result back, repeat — until the agent calls `emit` with
its structured result.

SAFETY (no box 2 yet): bash is sandboxed hard. A command must (1) contain no shell
metacharacters and (2) match an allow pattern derived from the agent's skills'
`allowed-tools` frontmatter. It runs with shell=False (shlex.split), a timeout, and
writes are OFF unless explicitly enabled. So an agent can only run the exact commands
its skills permit — on box 1 that means read-only skills like cfs-validate /
run-evolve-tests. Real mutation belongs on the disposable box 2 (EVOLVE.md §5).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess

import yaml

from apps.evolve.agents.base import AgentSpec, AgentResult
from apps.evolve.agents.runner import estimate_cost

_META_CHARS = [";", "|", "&", "`", "$(", ">", "<", "\n", "&&", "||"]


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #
def load_skill(name: str, skills_dir: str) -> dict:
    """Return {name, body, allow:[bash patterns]} for a .claude/skills/<name>/SKILL.md."""
    path = os.path.join(skills_dir, name, "SKILL.md")
    if not os.path.exists(path):
        return {"name": name, "body": "", "allow": []}
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    fm, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
        body = m.group(2)
    allowed = fm.get("allowed-tools", "")
    items = allowed if isinstance(allowed, list) else [allowed]
    allow = []
    for it in items:
        for bm in re.findall(r"Bash\(([^)]*)\)", str(it)):
            allow.append(bm.strip())
    return {"name": name, "body": body.strip(), "allow": allow}


def gather_skills(spec: AgentSpec, skills_dir: str) -> list[dict]:
    return [load_skill(s, skills_dir) for s in spec.skills]


# --------------------------------------------------------------------------- #
# Sandboxed tools
# --------------------------------------------------------------------------- #
def run_bash(cmd: str, allow: list[str], *, cwd: str, timeout: int = 60) -> str:
    cmd = cmd.strip()
    if any(mc in cmd for mc in _META_CHARS):
        return "DENIED: shell metacharacters are not allowed (run a single command)."
    if not any(fnmatch.fnmatch(cmd, pat) for pat in allow):
        return f"DENIED: command not permitted by this agent's skills. Allowed: {allow}"
    # Controlled env: never propagate the harness's live-test / network flags into a
    # sandboxed agent subprocess (else a `run-evolve-tests` skill would re-trigger
    # live API tests recursively). Strip them.
    env = {k: v for k, v in os.environ.items()
           if k not in ("EVOLVE_LIVE_TESTS",)}
    try:
        r = subprocess.run(shlex.split(cmd), cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, env=env)
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        return f"[exit {r.returncode}]\n{out}"[:6000]
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def read_file(path: str, *, cwd: str) -> str:
    full = os.path.realpath(os.path.join(cwd, path))
    if not full.startswith(os.path.realpath(cwd)):
        return "DENIED: path escapes the repository."
    if not os.path.exists(full):
        return f"NOT FOUND: {path}"
    if os.path.isdir(full):
        try:
            return f"{path} is a DIRECTORY. Contents:\n" + "\n".join(sorted(os.listdir(full)))
        except OSError as e:
            return f"{path} is a directory ({e})"
    with open(full, encoding="utf-8", errors="replace") as fh:
        return fh.read()[:8000]


def write_file(path: str, content: str, *, cwd: str) -> str:
    """Write a file, bounded to cwd (the feature worktree). Only offered when
    allow_writes=True — i.e. when cwd is an isolated, disposable checkout."""
    full = os.path.realpath(os.path.join(cwd, path))
    if not full.startswith(os.path.realpath(cwd)):
        return "DENIED: path escapes the workspace."
    os.makedirs(os.path.dirname(full) or cwd, exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content)
    return f"wrote {path} ({len(content)} bytes)"


def edit_file(path: str, old_string: str, new_string: str, *, cwd: str) -> str:
    """Surgical edit: replace a unique `old_string` with `new_string` in an existing
    file. Bounded to cwd (the feature worktree). This is how a code-acting agent
    changes a LARGE file without re-emitting the whole thing (write_file is
    overwrite-only and would blow the token budget on a 500-line module)."""
    full = os.path.realpath(os.path.join(cwd, path))
    if not full.startswith(os.path.realpath(cwd)):
        return "DENIED: path escapes the workspace."
    if not os.path.exists(full):
        return f"NOT FOUND: {path} (use write_file to create it)"
    with open(full, encoding="utf-8") as fh:
        content = fh.read()
    n = content.count(old_string)
    if n == 0:
        return "NO MATCH: old_string not found (it must match the file exactly)."
    if n > 1:
        return f"AMBIGUOUS: old_string appears {n} times; add surrounding context to make it unique."
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content.replace(old_string, new_string, 1))
    return f"edited {path}"


# --------------------------------------------------------------------------- #
# The backend
# --------------------------------------------------------------------------- #
class ToolUseBackend:
    def __init__(self, client=None, *, repo_root: str = ".",
                 skills_dir: str = ".claude/skills", max_turns: int = 10,
                 allow_writes: bool = False):
        self._client = client
        self.repo_root = repo_root
        self.skills_dir = skills_dir
        self.max_turns = max_turns
        self.allow_writes = allow_writes

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _tools(self, spec: AgentSpec):
        tools = [
            {"name": "bash", "description": "Run ONE shell command (no pipes/chaining). "
             "Only commands permitted by your skills will execute.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                              "required": ["command"], "additionalProperties": False}},
            {"name": "read_file", "description": "Read a file in the repository.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                              "required": ["path"], "additionalProperties": False}},
            {"name": "emit", "description": "Return your final structured result. Call this when done.",
             "input_schema": spec.output_schema},
        ]
        if self.allow_writes:
            tools.insert(2, {"name": "write_file",
                             "description": "Create or fully overwrite a file. Prefer edit_file for "
                             "changing an existing file — overwriting a large file is token-expensive.",
                             "input_schema": {"type": "object", "properties": {
                                 "path": {"type": "string"}, "content": {"type": "string"}},
                                 "required": ["path", "content"], "additionalProperties": False}})
            tools.insert(3, {"name": "edit_file",
                             "description": "Surgically change an existing file: replace a unique "
                             "old_string with new_string. Use this for edits to large files.",
                             "input_schema": {"type": "object", "properties": {
                                 "path": {"type": "string"}, "old_string": {"type": "string"},
                                 "new_string": {"type": "string"}},
                                 "required": ["path", "old_string", "new_string"],
                                 "additionalProperties": False}})
        return tools

    def run(self, spec: AgentSpec, payload: dict, context: dict | None, model: str,
            system: str = "") -> AgentResult:
        try:
            client = self._get_client()
        except Exception as e:
            return AgentResult(spec.name, ok=False, error=f"{type(e).__name__}: {e}", model=model)

        skills = gather_skills(spec, self.skills_dir)
        allow = [p for sk in skills for p in sk["allow"]]
        skill_text = "\n\n".join(f"## Skill: {sk['name']}\n{sk['body']}" for sk in skills)
        sys_prompt = (system or spec.resolved_prompt()) + (
            "\n\n# Skills you may use (run their commands via the `bash` tool)\n" + skill_text
            if skill_text else "")
        user = (f"Input:\n{json.dumps(payload, indent=2, default=str)}\n\n"
                "Use bash/read_file as needed, then call `emit` with your result.")
        messages = [{"role": "user", "content": user}]
        in_tok = out_tok = 0
        transcript: list[str] = []

        for _ in range(self.max_turns):
            msg = client.messages.create(model=model, max_tokens=spec.max_tokens,
                                         system=sys_prompt, tools=self._tools(spec),
                                         messages=messages)
            in_tok += msg.usage.input_tokens
            out_tok += msg.usage.output_tokens
            tool_uses = [b for b in msg.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                break
            messages.append({"role": "assistant", "content": msg.content})
            results = []
            for b in tool_uses:
                if b.name == "emit":
                    cost = estimate_cost(model, in_tok, out_tok)
                    return AgentResult(spec.name, ok=True, output=b.input, model=model,
                                       input_tokens=in_tok, output_tokens=out_tok,
                                       cost_usd=cost, raw_text="\n".join(transcript))
                try:
                    if b.name == "bash":
                        cmd = b.input.get("command", "")
                        res = run_bash(cmd, allow, cwd=self.repo_root)
                        transcript.append(f"$ {cmd}\n{res[:500]}")
                    elif b.name == "read_file":
                        res = read_file(b.input.get("path", ""), cwd=self.repo_root)
                        transcript.append(f"read {b.input.get('path','')}")
                    elif b.name == "write_file" and self.allow_writes:
                        res = write_file(b.input.get("path", ""), b.input.get("content", ""),
                                         cwd=self.repo_root)
                        transcript.append(res)
                    elif b.name == "edit_file" and self.allow_writes:
                        res = edit_file(b.input.get("path", ""), b.input.get("old_string", ""),
                                        b.input.get("new_string", ""), cwd=self.repo_root)
                        transcript.append(res)
                    else:
                        res = f"unknown tool {b.name}"
                except Exception as e:
                    # A tool error must NOT crash the agent loop — hand it back so the
                    # model can recover (e.g. it read_file'd a directory).
                    res = f"ERROR running {b.name}: {type(e).__name__}: {e}"
                    transcript.append(res)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": res})
            messages.append({"role": "user", "content": results})

        cost = estimate_cost(model, in_tok, out_tok)
        return AgentResult(spec.name, ok=False, model=model, input_tokens=in_tok,
                           output_tokens=out_tok, cost_usd=cost,
                           raw_text="\n".join(transcript),
                           error=f"did not emit within {self.max_turns} turns")
