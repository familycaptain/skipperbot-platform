"""The subconscious metabolizers — Phase 4 (specs/CONSCIOUSNESS.md §13, Q5, Q6).

Two background jobs over the consciousness log, both invoked from the memory
domain's cycle (the 24/7 subconscious heartbeat), both gated by the
subconscious metabolizers (always on since Phase 5b):

1. ``embed_log_batch()`` — the async embedding backfill (§11.9: nothing
   expensive rides inside the append; embeddings arrive here, later). Skips
   ``event`` rows (low retrieval value) and trivial content; observes the
   ~2s lagged-cursor discipline (§11.9 skew rule).

2. ``maybe_summarize()`` — the rolling summary checkpoints (Q5):
   **cumulative-style** (each summary reads the previous summary + the span
   since — open loops carry forward), **global + per-active-person scopes**,
   written as ``kind=summary`` rows with ``payload.covers_from_seq/covers_to_seq``.
   Default span 50 events (BELOW the 60-event timeline window so the §12.3
   no-gap invariant holds: anything the window trims is already summarized;
   Q5's ~150 was a placeholder pre-measurement), 24h clock backstop.

Neither speaks. Summary rows surface only through context assembly.
"""

import logging

logger = logging.getLogger("platform.summarizer")

SKIPPER = "skipper"
SYSTEM = "system"

_MIN_CONTENT_CHARS = 20
_EMBED_BATCH = 20
_SPAN_CAP = 300              # max events consumed by one summary pass
_KEEP_TAIL = 30              # newest events NEVER summarized — the live verbatim
                             # window keeps full fidelity; they summarize later
_BACKSTOP_MIN_EVENTS = 10    # 24h backstop still needs something to say
_PERSON_MIN_EVENTS = 5

_SUMMARY_GUIDANCE = (
    "You are Skipper's subconscious, consolidating the household timeline into "
    "a rolling summary. You get the PREVIOUS summary and the NEW events since. "
    "Write the updated summary: carry forward still-relevant context and open "
    "loops from the previous summary, fold in what the new events add, drop "
    "what's resolved or stale. Keep concrete dates and times that matter "
    "(deadlines, planned follow-ups, when things happened) — downstream readers "
    "reason about timing from them. Dense, factual, third-person, no preamble, "
    "under 250 words."
)


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _summary_span() -> int:
    try:
        from app_platform import settings as _settings
        return int(_settings.get("consciousness_summary_span", scope="platform", default=50) or 50)
    except Exception:
        return 50


def _vec(embedding: list[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in embedding) + "]"


# ── 1. embedding backfill ────────────────────────────────────────────────────

def embed_log_batch(limit: int = _EMBED_BATCH) -> int:
    """Embed a batch of unembedded log rows. Returns rows embedded."""
    from data_layer.db import fetch_all, execute
    from memory_store import get_embedding

    rows = fetch_all(
        "SELECT id, content FROM consciousness_log "
        "WHERE embedding IS NULL AND kind != 'event' "
        "  AND length(content) >= %s "
        "  AND created_at < now() - interval '2 seconds' "
        "ORDER BY seq ASC LIMIT %s",
        (_MIN_CONTENT_CHARS, limit),
    )
    done = 0
    for row in rows:
        try:
            emb = get_embedding(row["content"][:4000])
            if not emb:
                continue
            execute("UPDATE consciousness_log SET embedding = %s::vector WHERE id = %s",
                    (_vec(emb), row["id"]))
            done += 1
        except Exception as exc:
            logger.warning("SUMMARIZER: embed failed for %s: %s", row["id"], exc)
            break  # provider trouble — retry next cycle, don't hammer
    if done:
        logger.info("SUMMARIZER: embedded %d log row(s)", done)
    return done


# ── 2. rolling summaries (Q5) ────────────────────────────────────────────────

def _latest_summary(person: str | None):
    from data_layer.db import fetch_one
    if person:
        return fetch_one(
            "SELECT * FROM consciousness_log WHERE kind='summary' "
            "AND payload->>'scope' = 'person' AND who_to = %s "
            "ORDER BY seq DESC LIMIT 1", (person,))
    return fetch_one(
        "SELECT * FROM consciousness_log WHERE kind='summary' "
        "AND payload->>'scope' = 'global' ORDER BY seq DESC LIMIT 1")


def _covers_to(summary_row) -> int:
    import json
    if not summary_row:
        return 0
    p = summary_row.get("payload") or {}
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            p = {}
    return int(p.get("covers_to_seq") or 0)


def _render_span(rows: list[dict]) -> str:
    from app_platform.context import event_stamp
    lines = []
    for r in rows:
        who = r["who_from"] + (f"→{r['who_to']}" if r.get("who_to") else "")
        lines.append(f"{event_stamp(r)}[{r['kind']}/{r['domain']}] {who}: "
                     f"{(r['content'] or '')[:200]}")
    return "\n".join(lines)


async def _write_summary(scope: str, person: str | None, prev_text: str,
                         span_rows: list[dict]) -> None:
    import asyncio
    import agent_loop
    from app_platform.consciousness import log_event

    label = f"{person}'s recent thread" if person else "the household"
    user = (f"PREVIOUS SUMMARY of {label}:\n{prev_text or '(none yet)'}\n\n"
            f"NEW EVENTS since:\n{_render_span(span_rows)}\n\n"
            f"Write the updated rolling summary of {label}.")
    result = await agent_loop.run(
        messages=[{"role": "system", "content": _SUMMARY_GUIDANCE},
                  {"role": "user", "content": user}],
        tools=None, tier="fast", max_turns=1, max_tool_calls=0,
    )
    text = (result.response_text or "").strip()
    if not text:
        return
    await asyncio.to_thread(
        lambda: log_event(
            kind="summary", who_from=SKIPPER, who_to=person,
            domain="system", content=text,
            payload={"scope": scope,
                     "covers_from_seq": span_rows[0]["seq"],
                     "covers_to_seq": span_rows[-1]["seq"]},
        ))
    logger.info("SUMMARIZER: wrote %s summary covering seq %s..%s",
                scope if not person else f"person:{person}",
                span_rows[0]["seq"], span_rows[-1]["seq"])


async def maybe_summarize() -> int:
    """Write global (+ per-active-person) summary checkpoints when due (Q5)."""
    import asyncio
    from data_layer.db import fetch_all

    span_trigger = _summary_span()
    last_global = await asyncio.to_thread(_latest_summary, None)
    since = _covers_to(last_global)

    rows = await asyncio.to_thread(
        fetch_all,
        "SELECT seq, id, kind, who_from, who_to, domain, content, created_at "
        "FROM consciousness_log "
        "WHERE seq > %s AND kind != 'summary' "
        "  AND seq <= (SELECT COALESCE(MAX(seq),0) - %s FROM consciousness_log) "
        "ORDER BY seq ASC LIMIT %s",
        (since, _KEEP_TAIL, _SPAN_CAP),
    )
    if not rows:
        return 0

    over_span = len(rows) >= span_trigger
    stale = False
    if not over_span and len(rows) >= _BACKSTOP_MIN_EVENTS and last_global:
        from datetime import datetime, timezone, timedelta
        created = last_global.get("created_at")
        if created and (datetime.now(timezone.utc) - created) > timedelta(hours=24):
            stale = True
    if not over_span and not stale and last_global is not None:
        return 0
    if last_global is None and len(rows) < _BACKSTOP_MIN_EVENTS:
        return 0  # brand-new log — wait for enough to say anything

    written = 0
    await _write_summary("global", None, (last_global or {}).get("content") or "", rows)
    written += 1

    # per-person: humans active in the span
    from data_layer.users import get_human_users
    humans = {(u.get("name") or "").lower() for u in await asyncio.to_thread(get_human_users)}
    active: dict[str, list[dict]] = {}
    for r in rows:
        for who in (r.get("who_from"), r.get("who_to")):
            w = (who or "").lower()
            if w in humans:
                active.setdefault(w, []).append(r)
    for person, slice_rows in active.items():
        if len(slice_rows) < _PERSON_MIN_EVENTS:
            continue
        prev_p = await asyncio.to_thread(_latest_summary, person)
        await _write_summary("person", person, (prev_p or {}).get("content") or "", slice_rows)
        written += 1
    return written


async def run_subconscious_pass() -> dict:
    """One metabolizer pass: embed a batch + summarize if due. Cheap when idle."""
    import asyncio
    embedded = await asyncio.to_thread(embed_log_batch)
    summaries = await maybe_summarize()
    return {"embedded": embedded, "summaries": summaries}
