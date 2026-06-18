# Evolve

Skipper's self-maintenance workshop. Evolve is where **you, the operator**, review
and approve the changes Skipper proposes to its own code — one issue at a time. You
don't write code here; you read what Skipper's agents have prepared and make the
call at each decision point.

## Overview

When a bug or feature request comes in (filed on GitHub, or by you), Evolve runs it
through an automated software pipeline — understanding the codebase, designing an
approach, writing the spec, building it, and reviewing it — and **pauses at gates**
to ask for your decision. Nothing reaches the live system without you approving it,
and even an approved change isn't "done" until you've tested it for real.

Each item in Evolve is **one issue**, and it keeps **one conversation** for its
whole life — so when you send something back, Skipper resumes with full context
rather than starting over.

## The three gates

Evolve stops and waits for you at three points. At each, you read a **packet**
(Skipper's summary of the work) and choose an action.

### Gate 1 — review the plan
Before any code is written, the agents ground themselves in the codebase, decide an
approach, and draft the spec. The packet shows you:

- a **summary** of the work and why it matters,
- the **Lead's recommendation** — the suggested action, *why*, and a plain
  "today it does X → after this it'll do Y",
- **Placement / dependency-rule notes** — a read-only sketch of *what code would
  change* (which files, added/modified) before a line is written,
- the **reviews** (architecture, security, interop, UX) and the priority call.

Your choices:
- **Approve** — proceed to build it.
- **Change** — send it back with a direction (e.g. pick one of the offered options);
  Skipper re-specs along that line.
- **Reject** — not the right change; it's torn down.
- **Abandon** — drop the item entirely.

### Gate 2 — review the build
After Skipper implements the change and runs validation, you see what was built and
whether validation passed, plus a recommendation. **Approve** merges it to the
`release` branch; **Reject** sends it back. A build that didn't validate can never
reach a green Gate 2.

### Gate 3 — verify it live
**Merging is not "done."** The change is on `release` for you to actually try on
your system. When you've tested it:

- **Works** — closes the issue. Done.
- **Still broken** — reopens the *same* conversation so Skipper keeps going with
  everything it already knows, rather than from scratch.

## Activity / live build

While Skipper works an item, the **Activity** view shows per-agent panels — each
agent's progress, the tools it called, and its output — so you can watch the build
happen and see exactly what each step concluded.

## Filing an issue

You can hand Evolve work directly. Operator-filed items are treated as authoritative
— they skip the "reject as out-of-scope" triage that external requests get, because
you're the one who decides what's in scope. (Issues filed on the project's GitHub are
ingested automatically.)

## Tips

- **Read the Lead's recommendation first** — it's the one-paragraph "what and why"
  and usually tells you whether this is an easy Approve.
- **Use Change, not Reject, when the idea is right but the direction is wrong** —
  Reject tears the work down; Change keeps the thread and redirects it.
- **Always do Gate 3 on a real device/scenario** — the live test is the whole point;
  "it merged" only means it's ready *for* you to test.
