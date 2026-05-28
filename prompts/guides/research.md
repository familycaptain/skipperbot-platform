# Research Guide

## Overview

Research runs as a **background job** — it does NOT happen in the chat turn.
When a user asks you to research something, queue a **single** research job and let them
know it's running. They'll be notified when it's done.

**IMPORTANT: Always use ONE job.** The pipeline supports up to 20 sources per job.
Never split research into multiple passes or jobs — a single job produces one unified
set of findings. The intelligent planner handles query diversity automatically.

## How It Works

1. User says "research X" / "look into X" / "find out about X"
2. You call `start_research(query, requested_by, ...)`
3. A job (`j-*`) is created with status `queued`
4. The scheduler picks it up (within ~30 seconds) and runs it in the background
5. **Planning**: An intelligent research planner (SMART_MODEL) analyzes the query
   (and optional spec doc) and generates 2-4 strategic, targeted search queries
6. **Search**: Each planned query is executed against the Brave Search API
7. **Fetch & Summarize**: Top pages are fetched and summarized by LLM
8. **Synthesize**: SMART_MODEL produces a comprehensive, publication-quality document
9. **Output**: One or two documents are created:
   - **Findings doc** (`d-*`) — the research report (always created)
   - **Data doc** (`d-*`) — structured JSON data, if the synthesis produced any
     (automatically extracted from ```json blocks in the synthesis)
10. Both docs are linked to `related_entity_id` if provided
11. Full document content is delivered via Discord DM (auto-chunked)
12. Pushover gets a short alert (Alice only)
13. User can then discuss, refine, or append to the doc

## Starting Research

```
start_research(
    query="best solar panels for residential use 2026",
    requested_by="alice",
    num_sources="10",          # 1-20, default 5
    tags="solar,home",         # comma-separated, added to output doc
    related_entity_id="p-abc", # optional, links output doc(s) to entity
    scheduled_for="",          # ISO datetime or empty for immediate
    spec_doc_id="",            # optional d-* doc with detailed research specs
)
```

### Using a Specification Document

When the user has detailed research requirements written in a Document (`d-*`),
pass it as `spec_doc_id`. The planner reads the doc and uses its content to
generate more targeted queries. The synthesizer also sees the spec doc and
follows its output format requirements (e.g., specific sections, JSON schema).

```
start_research(
    query="Forward-looking portfolio recommendation per spec doc",
    requested_by="alice",
    num_sources="20",
    spec_doc_id="d-91844d6a",    # the spec doc with detailed requirements
    related_entity_id="p-abc",
)
```

**When to use spec_doc_id:**
- User says "research based on this document" → pass the doc ID
- User has written detailed criteria, schemas, or output requirements
- The research needs to follow a specific methodology or format

### Scheduling for Later

If the user wants research to start at a specific time:
- "Research this tomorrow morning" → `scheduled_for="2026-02-09T08:00:00-06:00"`
- "Look into this tonight" → `scheduled_for="2026-02-08T19:00:00-06:00"`

## Monitoring

- `check_research(job_id)` — see status, progress, sources read
- `list_research_jobs()` — see all research jobs
- `list_research_jobs(status_filter="running")` — see active research

## Cancellation

- `cancel_research(job_id, cancelled_by)` — stops the job
- If currently running, it stops after the current source finishes
- User is still notified that it was cancelled

## After Completion

The output is one or two standard `d-*` docs. Use doc tools to work with them:
- `get_doc(doc_id)` — read the full research document
- `append_to_doc(doc_id, content, user)` — add follow-up notes
- `search_docs(query)` — find research docs later
- `update_doc_meta(doc_id, user, tags="...")` — retag or relink
- `refine_research(doc_id, instructions, user)` — do follow-up research and create a revised version

### Automatic JSON Data Document

If the synthesis output contains structured data in a ```json code block (e.g.,
a portfolio allocation, data table, or config), the pipeline **automatically**
extracts it into a separate data document:
- **Findings doc**: "Research: [topic]" — the text report (JSON removed)
- **Data doc**: "Research Data: [topic]" — just the JSON, tagged `data, json`
- Both are linked to `related_entity_id`
- The notification mentions both document IDs

This is automatic — you don't need to do anything special. If the spec doc or
query calls for JSON output, the synthesizer will produce it and the pipeline
will split it out.

## Refining / Iterating on Research

Research is not a one-shot process. Use `refine_research` when the user wants to:
- Expand a section that wasn't detailed enough
- Add information that the original research missed
- Dig deeper into a specific aspect of the findings
- Update the document with newer information

### How refinement works:
1. User says "expand the section on side effects" (referencing a doc)
2. You call `refine_research(doc_id, instructions, requested_by, ...)`
3. A refine job is queued and picked up by the scheduler
4. The pipeline reads the original doc, generates **focused search queries** based on the
   instructions, does targeted web research, and produces a **revised version** of the doc
5. A new `d-*` document is created (v2, v3, etc.) — the original is **never modified**
6. The new doc is linked to the original via `parent_doc_id` and `has_revision` link
7. Full revised content is delivered via Discord DM

```
refine_research(
    doc_id="d-fd9510f3",
    instructions="expand the section on clinical studies and add pricing info",
    requested_by="alice",
    num_sources="5",     # 1-20, default 3
)
```

### Version chain
Each refinement increments the version and links back:
- `d-abc` (v1, original) → `d-def` (v2, refined) → `d-ghi` (v3, refined again)
- Use `get_entity_links(doc_id)` to see the revision chain
- Original documents are always preserved

## Natural Language Patterns

| User says | Action |
|-----------|--------|
| "research solar panels" | `start_research("solar panels", user, num_sources="10")` |
| "look into the best options for X" | `start_research("best options for X", user)` |
| "research based on this document" | `start_research("...", user, spec_doc_id="d-...")` |
| "find out about X and link it to the home project" | `start_research("X", user, related_entity_id="p-...")` |
| "research X with 20 sources" | `start_research("X", user, num_sources="20")` — ONE job, not two |
| "how's that research going?" | `check_research(job_id)` or `list_research_jobs(status_filter="running")` |
| "cancel the research" | `cancel_research(job_id, user)` |
| "show me what the research found" | `get_doc(doc_id)` (from the job's output) |
| "research X tomorrow morning" | `start_research("X", user, scheduled_for="...")` |
| "expand on the side effects section" | `refine_research(doc_id, "expand the side effects section", user)` |
| "that doc needs more detail on pricing" | `refine_research(doc_id, "add more detail on pricing and availability", user)` |
| "dig deeper into the clinical studies" | `refine_research(doc_id, "more clinical studies and data", user)` |
| "revise the research with newer sources" | `refine_research(doc_id, "find more recent sources and update findings", user)` |

## What the Output Doc Contains

- **Header** — query, timestamp, source count, strategy, spec doc reference
- **Executive Summary** — concise overview of findings (2-3 paragraphs)
- **Key Findings** — major takeaways organized by theme, with data points
- **Detailed Analysis** — deeper exploration with cross-referenced evidence
- **Sources** — numbered list with [title](url) and what each contributed
- **Recommendations / Next Steps** — actionable conclusions
- **JSON data block** (if applicable) — auto-extracted into separate data doc

## Presenting Research Results

**CRITICAL: Never re-summarize a research document.** The doc is already curated and
summarized by the research pipeline. When the user asks to see research results:

- Show the **full document content** verbatim — do NOT condense, re-summarize, or paraphrase
- The completion notification already delivers the full doc via Discord DM
- If the user asks to see it again, use `get_doc(doc_id)` and present the content as-is
- If you need to highlight a specific section, quote it directly from the doc

## Important Notes

- **ONE job per research request** — never split into multiple passes or jobs
- Up to **20 sources** per job (the planner handles query diversity automatically)
- The **research planner** (SMART_MODEL) generates strategic search queries — you
  don't need to craft the search terms yourself, just pass the user's intent
- **Spec docs** provide detailed requirements to the planner and synthesizer
- Synthesis uses **SMART_MODEL** for publication-quality output
- Summarization uses DUMB_MODEL for cost efficiency
- Each source page is capped at ~6000 chars for LLM context
- The pipeline checks for cancellation between each source
- Completion notification delivers full doc via Discord DM (auto-chunked)
- Pushover gets a short alert (Alice only)
- All research docs are auto-tagged with "research"
