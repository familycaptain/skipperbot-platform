"""Job Handlers — Bridges existing runners to the unified job dispatcher.

Each handler is an async function with signature:
    async def handler(job: dict, ctx: JobContext) -> str

Handlers are registered at import time via register_all_handlers().
"""

from config import logger
from config import TIMEZONE as _CFG_TZ
from job_dispatcher import register_handler, JobContext


# ---------------------------------------------------------------------------
# Research handler
# ---------------------------------------------------------------------------

def _handle_research(job: dict, ctx: JobContext) -> str:
    """Run a research job (synchronous — runs in thread pool)."""
    from research_runner import _run_research_pipeline
    ctx.update_progress(5, "Starting research pipeline...")
    result = _run_research_pipeline(job)
    doc_id = result.get("doc_id", "")
    return f"Research complete: {doc_id}" if doc_id else "Research completed"


# ---------------------------------------------------------------------------
# Refine handler
# ---------------------------------------------------------------------------

def _handle_refine(job: dict, ctx: JobContext) -> str:
    """Run a refine job (synchronous — runs in thread pool)."""
    from research_runner import _run_refine_pipeline
    ctx.update_progress(5, "Starting refine pipeline...")
    result = _run_refine_pipeline(job)
    return f"Refine complete" if result.get("success") else f"Refine failed: {result.get('error', '?')}"


# ---------------------------------------------------------------------------
# Print handler
# ---------------------------------------------------------------------------

def _handle_print(job: dict, ctx: JobContext) -> str:
    """Run a print job (synchronous — runs in thread pool)."""
    from print_runner import _run_print_pipeline
    ctx.update_progress(10, "Printing...")
    result = _run_print_pipeline(job)
    if result.get("success"):
        return f"Printed via {result.get('method', '?')}"
    return f"Print failed: {result.get('error', '?')}"


# ---------------------------------------------------------------------------
# PM (Project Manager) handler
# ---------------------------------------------------------------------------

async def _handle_pm(job: dict, ctx: JobContext) -> str:
    """Run the Project Manager daily cycle."""
    from apps.goals.pm_runner import check_and_run_pm
    ctx.update_progress(10, "Running PM cycle...")
    await check_and_run_pm(force=True)
    return "PM cycle complete"


async def _handle_pm_check(job: dict, ctx: JobContext) -> str:
    """Run a lighter PM check-in between daily scrums."""
    from apps.goals.pm_runner import run_pm_check
    ctx.update_progress(10, "Running PM check-in...")
    await run_pm_check()
    return "PM check-in complete"


# ---------------------------------------------------------------------------
# Investment handler
# ---------------------------------------------------------------------------

async def _handle_investment(job: dict, ctx: JobContext) -> str:
    """Run the investment analysis pipeline (delegated to app package)."""
    from apps.investment.handlers import handle_investment
    return await handle_investment(job, ctx)


# ---------------------------------------------------------------------------
# Rebalance handler
# ---------------------------------------------------------------------------

async def _handle_rebalance(job: dict, ctx: JobContext) -> str:
    """Run a portfolio rebalance (delegated to app package)."""
    from apps.investment.handlers import handle_rebalance
    return await handle_rebalance(job, ctx)


# ---------------------------------------------------------------------------
# Backup handler
# ---------------------------------------------------------------------------

def _handle_backup(job: dict, ctx: JobContext) -> str:
    """Run a backup job (synchronous — runs in thread pool)."""
    from backup_runner import run_backup
    ctx.update_progress(5, "Starting backup...")
    return run_backup(job, ctx)


def _handle_backup_check(job: dict, ctx: JobContext) -> str:
    """Check if today's backup ran successfully; notify if failed or missing."""
    from datetime import date
    from zoneinfo import ZoneInfo
    from data_layer.db import fetch_all
    from notification_store import create_notification

    today = date.today()
    ctx.update_progress(20, "Querying today's backup records...")

    rows = fetch_all(
        """
        SELECT id, status, error, started_at
        FROM backups
        WHERE (started_at AT TIME ZONE %s)::date = %s
        ORDER BY started_at DESC
        """,
        (_CFG_TZ, today,),
    )

    ctx.update_progress(60, f"Found {len(rows)} backup record(s) for today")

    if not rows:
        create_notification(
            recipient="alice",
            message="Backup did not run today. No backup record found (expected at 2:00 AM CT).",
            source_type="backup_check",
            source_id="",
            channel="both",
            delivered=False,
        )
        logger.warning("BACKUP_CHECK: No backup record found for today — notification sent")
        return "No backup found for today — notification sent"

    completed = [r for r in rows if r["status"] == "completed"]
    if completed:
        ctx.update_progress(100, "Backup completed successfully")
        logger.info("BACKUP_CHECK: Today's backup OK (%s)", completed[0]["id"])
        return f"Backup OK: {completed[0]['id']}"

    latest = rows[0]
    status = latest["status"]
    error = (latest.get("error") or "").strip()

    if status == "failed":
        msg = "Backup failed today."
        if error:
            msg += f" Error: {error[:300]}"
        create_notification(
            recipient="alice",
            message=msg,
            source_type="backup_check",
            source_id=latest["id"],
            channel="both",
            delivered=False,
        )
        logger.warning("BACKUP_CHECK: Backup failed — notification sent (%s)", latest["id"])
        return "Backup failed — notification sent"

    if status == "skipped":
        logger.info("BACKUP_CHECK: Backup was skipped (disabled) — no notification")
        return "Backup skipped (disabled) — no notification sent"

    if status == "running":
        logger.info("BACKUP_CHECK: Backup still running at check time (%s) — no notification", latest["id"])
        return f"Backup still running ({latest['id']}) — no action taken"

    return f"Backup status: {status}"


# Email handler now auto-registered from apps/email/manifest.yaml


# ---------------------------------------------------------------------------
# Equity Curve handler
# ---------------------------------------------------------------------------

async def _handle_equity_curve(job: dict, ctx: JobContext) -> str:
    """Run an equity curve tick (delegated to app package)."""
    from apps.investment.handlers import handle_equity_curve
    return await handle_equity_curve(job, ctx)


# ---------------------------------------------------------------------------
# Folder Intelligence handler
# ---------------------------------------------------------------------------

def _handle_folder_intelligence(job: dict, ctx: JobContext) -> str:
    """Process a folder item for intelligence extraction (sync — runs in thread pool)."""
    from folder_intelligence import process_folder_item
    config = job.get("config") or {}
    folder_id = config.get("folder_id", "")
    entity_id = config.get("entity_id", "")
    if not folder_id or not entity_id:
        return "Missing folder_id or entity_id in job config"
    ctx.update_progress(10, f"Processing {entity_id} in {folder_id}...")
    result = process_folder_item(folder_id, entity_id)
    if result.get("error") and result["error"] != "skipped:unchanged":
        return f"Failed: {result['error']}"
    return f"Done: {result['chunks']} chunks, {result['facts']} facts"


# ---------------------------------------------------------------------------
# Evolve unit handler (self-improvement LLM calls)
# ---------------------------------------------------------------------------

async def _handle_evolve_unit(job: dict, ctx: JobContext) -> str:
    """Execute a single Evolve work unit — one focused LLM call.

    Each unit has a prompt_template and context in its config. The handler
    loads the template, builds messages, runs agent_loop, and stores
    structured output in the job's output JSONB.

    Synthesis units wait for all sibling units to complete first.
    """
    config = job.get("config") or {}
    is_synthesis = config.get("is_synthesis", False)

    if is_synthesis:
        return await _handle_evolve_synthesis(job, ctx, config)

    import agent_loop
    from config import SMART_MODEL

    ctx.update_progress(5, "Loading prompt and context...")

    # Load focused prompt template
    prompt_template = config.get("prompt_template", "")
    context = config.get("context", {})
    prompt_text = _load_evolve_prompt(prompt_template)

    # Build messages — inject tool budget so LLM plans efficiently
    extra_tools = config.get("tools", [])
    tool_guidance = (
        "## Tool Budget\n"
        "You have a maximum of **30 tool calls** across this entire analysis.\n"
        "Plan your investigation efficiently:\n"
        "- Use grep to locate relevant code, then read only the key sections.\n"
        "- Do NOT exhaustively read every file — focus on what matters.\n"
        "- Produce your JSON output BEFORE running out of tool calls.\n"
        "If you are at ~25 tool calls, STOP investigating and output your findings immediately.\n"
    )
    if "internet_search" in extra_tools:
        tool_guidance += (
            "\n## Web Research (REQUIRED)\n"
            "You have `internet_search` and `curl_request` tools available.\n"
            "**You MUST use internet_search at least 2-3 times** to research real data:\n"
            "- Business ideas and automations an AI agent can run autonomously\n"
            "- Market sizes, pricing, competitor analysis\n"
            "- API availability and costs for integrations\n"
            "- Current trends relevant to the topic\n"
            "Do NOT rely solely on your training data — search for current information.\n"
        )
    system_text = prompt_text + "\n\n" + tool_guidance
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": _build_evolve_user_message(prompt_template, context)},
    ]

    # Resolve tools for this unit
    tools, tool_dispatch = await _get_evolve_tools(extra_tools)
    logger.info("EVOLVE_UNIT[%s]: Resolved %d tools (extra: %s)",
                config.get("prompt_template", ""), len(tools),
                extra_tools or "none")

    ctx.update_progress(10, "Running LLM analysis...")

    result = await agent_loop.run(
        messages=messages,
        tools=tools,
        model=SMART_MODEL,
        max_turns=8,
        max_tool_calls=30,
        tool_dispatch=tool_dispatch,
    )

    ctx.update_progress(90, "Processing output...")

    # Store structured output
    findings = _parse_evolve_output(result.response_text)
    ctx.update_output(
        findings=findings,
        tokens_used=result.prompt_tokens + result.completion_tokens,
        response=result.response_text or "",
    )

    # Phase 5 post-processing: actually create/update evolve items and links
    if prompt_template == "phase_5_propose":
        await _execute_propose_actions(findings, job, ctx)

    # Reconcile post-processing: update evolve item statuses based on recommendations
    if prompt_template == "phase_1_reconcile":
        await _execute_reconcile_actions(findings, ctx)

    return f"Completed: {len(findings)} findings, {result.prompt_tokens + result.completion_tokens} tokens"


async def _execute_propose_actions(findings: list[dict], job: dict, ctx: JobContext):
    """Post-process Phase 5 output: create/update evolve items + link to goals."""
    import asyncio
    from data_layer.evolution import create_item, update_item, get_item
    from data_layer.links import create_link

    config = job.get("config", {})
    cycle_id = config.get("cycle_id", "")
    cycle_job_id = cycle_id  # cycle_job_id = the evolve_cycle job ID
    created = 0
    updated = 0
    skipped = 0
    linked = 0

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        action = finding.get("action", "create_item")

        try:
            if action == "skip":
                skipped += 1
                continue

            if action == "update_item":
                existing_id = finding.get("existing_item_id", "")
                if existing_id:
                    item_data = finding.get("item", {})
                    update_kwargs = {}
                    if item_data.get("title"):
                        update_kwargs["title"] = item_data["title"]
                    if item_data.get("body"):
                        update_kwargs["body"] = item_data["body"]
                    if item_data.get("impact"):
                        update_kwargs["impact"] = item_data["impact"]
                    if item_data.get("effort"):
                        update_kwargs["effort"] = item_data["effort"]
                    if item_data.get("category"):
                        update_kwargs["category"] = item_data["category"]
                    if update_kwargs:
                        await asyncio.to_thread(update_item, existing_id, **update_kwargs)
                        updated += 1
                        logger.info("EVOLVE: Updated evolve item %s", existing_id)

                    # Link to goal if specified
                    goal_id = finding.get("linked_goal_id")
                    project_id = finding.get("linked_project_id")
                    if goal_id:
                        await asyncio.to_thread(
                            create_link, existing_id, goal_id,
                            relation="implements", created_by="skipper")
                        linked += 1
                    if project_id:
                        await asyncio.to_thread(
                            create_link, existing_id, project_id,
                            relation="implements", created_by="skipper")
                        linked += 1
                continue

            if action in ("create_item", "status_update"):
                item_data = finding.get("item", {})
                if not item_data.get("title"):
                    continue

                new_item = await asyncio.to_thread(
                    create_item,
                    item_type=item_data.get("type", "finding"),
                    title=item_data["title"],
                    body=item_data.get("body", ""),
                    impact=item_data.get("impact"),
                    effort=item_data.get("effort"),
                    category=item_data.get("category"),
                    created_by="skipper",
                    cycle_id=cycle_id,
                    cycle_job_id=cycle_job_id,
                    parent_id=item_data.get("parent_item_id"),
                    phase_origin="propose",
                )
                created += 1
                logger.info("EVOLVE: Created evolve item %s: %s",
                            new_item.get("id"), item_data["title"][:60])

                # Link to goal/project if specified
                new_id = new_item.get("id", "")
                goal_id = finding.get("linked_goal_id")
                project_id = finding.get("linked_project_id")
                if goal_id and new_id:
                    await asyncio.to_thread(
                        create_link, new_id, goal_id,
                        relation="implements", created_by="skipper")
                    linked += 1
                if project_id and new_id:
                    await asyncio.to_thread(
                        create_link, new_id, project_id,
                        relation="implements", created_by="skipper")
                    linked += 1

        except Exception as e:
            logger.warning("EVOLVE: Failed to process propose action: %s", e)

    ctx.update_output(
        items_created=created,
        items_updated=updated,
        items_skipped=skipped,
        items_linked=linked,
    )
    logger.info("EVOLVE: Phase 5 results — %d created, %d updated, %d skipped, %d linked",
                created, updated, skipped, linked)


async def _execute_reconcile_actions(findings: list[dict], ctx: JobContext):
    """Post-process reconcile output: update evolve item statuses."""
    import asyncio
    from data_layer.evolution import set_status

    status_map = {
        "complete": "completed",
        "defer": "deferred",
    }
    updated = 0

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        item_id = finding.get("item_id", "")
        recommendation = finding.get("recommendation", "keep")
        suggested = finding.get("suggested_status", "")

        if not item_id:
            continue

        # Only auto-update for clear recommendations
        if recommendation in ("complete", "defer") and suggested:
            try:
                await asyncio.to_thread(set_status, item_id, suggested)
                updated += 1
                logger.info("EVOLVE: Reconcile — %s → %s (%s)",
                            item_id, suggested, recommendation)
            except Exception as e:
                logger.warning("EVOLVE: Failed to update %s: %s", item_id, e)
        elif recommendation == "escalate":
            logger.info("EVOLVE: Reconcile — %s flagged for escalation: %s",
                        item_id, finding.get("recommendation_reason", ""))
        elif recommendation == "needs_goal":
            logger.info("EVOLVE: Reconcile — %s needs a linked goal created",
                        item_id)

    ctx.update_output(reconcile_updated=updated)
    logger.info("EVOLVE: Reconcile results — %d items updated", updated)


# Phase key → phase_origin label and default item type
PHASE_ITEM_CONFIG = {
    "phase_1_vision":          {"origin": "vision",     "default_type": "goal"},
    "phase_2_self_assessment": {"origin": "assessment",  "default_type": "finding"},
    "phase_3_gap_analysis":    {"origin": "gap",         "default_type": "finding"},
    "phase_4_planning":        {"origin": "planning",    "default_type": "proposal"},
    "phase_5_propose":         {"origin": "propose",     "default_type": "work_item"},
    "phase_1_act":             {"origin": "reconcile",   "default_type": "finding"},
}


async def _create_items_from_synthesis(
    findings: list[dict], phase_key: str, cycle_job_id: str, ctx: JobContext,
    cycle_id: str = "",
):
    """Create evolve items from synthesis findings for any phase.

    Two-pass creation: goals first (to get IDs), then proposals with resolved
    parent references.  The LLM can use ``parent_item_id: "new:N"`` where N is
    the 0-based index of a goal in the same findings array.

    Skips Phase 0 (feedback) and Phase 5 (propose) which have their own
    specialized item creation logic.
    """
    import asyncio
    from data_layer.evolution import create_item, update_item, list_items
    from data_layer.db import fetch_all

    # Skip phases that don't produce new items or have their own logic
    if phase_key in ("phase_0_feedback", "phase_5_propose"):
        return

    cfg = PHASE_ITEM_CONFIG.get(phase_key)
    if not cfg:
        return

    origin = cfg["origin"]
    default_type = cfg["default_type"]

    # Load existing items in this cycle to avoid duplicates
    existing = await asyncio.to_thread(
        fetch_all,
        "SELECT title FROM evolution_items WHERE cycle_job_id = %s",
        (cycle_job_id,),
    )
    existing_titles = {r["title"].lower().strip() for r in existing}

    valid_cats = {"codebase", "tooling", "capability", "integration",
                  "architecture", "family", "process", "documentation"}
    valid_types = {"finding", "proposal", "question", "goal",
                   "work_item", "status_update"}

    def _validate_finding(finding):
        """Extract and validate fields from a finding dict."""
        if not isinstance(finding, dict):
            return None
        title = finding.get("title", finding.get("summary", "")).strip()
        if not title:
            return None
        body = finding.get("summary", finding.get("body", ""))
        impact = finding.get("impact")
        if impact and impact.lower() not in ("low", "medium", "high"):
            impact = None
        effort = finding.get("effort")
        if effort and effort.lower() not in ("low", "medium", "high"):
            effort = None
        category = finding.get("category")
        if category and category.lower() not in valid_cats:
            category = None
        item_type = finding.get("type", default_type)
        if item_type not in valid_types:
            item_type = default_type
        parent_id = finding.get("parent_item_id") or finding.get("parent_id")
        action = finding.get("action", "create")
        existing_item_id = finding.get("existing_item_id", "")
        return {
            "title": title, "body": body, "impact": impact, "effort": effort,
            "category": category, "item_type": item_type, "parent_id": parent_id,
            "action": action, "existing_item_id": existing_item_id,
        }

    created = 0
    updated = 0
    skipped = 0
    # index → created item ID (for resolving "new:N" parent references)
    index_to_id: dict[int, str] = {}

    # --- Pass 1: updates + goals (items without "new:N" parent) ---
    for idx, finding in enumerate(findings):
        v = _validate_finding(finding)
        if not v:
            continue

        # Handle updates first (any type)
        if v["action"] == "update" and v["existing_item_id"]:
            try:
                update_kwargs = {}
                if v["body"]:
                    update_kwargs["body"] = v["body"]
                if v["impact"]:
                    update_kwargs["impact"] = v["impact"]
                if v["effort"]:
                    update_kwargs["effort"] = v["effort"]
                if v["category"]:
                    update_kwargs["category"] = v["category"]
                if v["parent_id"] and not str(v["parent_id"]).startswith("new:"):
                    update_kwargs["parent_id"] = v["parent_id"]
                if update_kwargs:
                    await asyncio.to_thread(
                        update_item, v["existing_item_id"], **update_kwargs
                    )
                    updated += 1
                    logger.info("EVOLVE: [%s] Updated existing item %s: %s",
                                origin, v["existing_item_id"], v["title"][:60])
                else:
                    skipped += 1
            except Exception as e:
                logger.warning("EVOLVE: [%s] Failed to update item %s: %s",
                               origin, v["existing_item_id"], e)
            continue

        # Defer items with "new:N" parent to pass 2
        if v["parent_id"] and str(v["parent_id"]).startswith("new:"):
            continue

        # Dedup
        if v["title"].lower().strip() in existing_titles:
            skipped += 1
            continue

        try:
            new_item = await asyncio.to_thread(
                create_item,
                item_type=v["item_type"],
                title=v["title"],
                body=v["body"] or "",
                impact=v["impact"],
                effort=v["effort"],
                category=v["category"],
                created_by="skipper",
                cycle_id=cycle_id,
                cycle_job_id=cycle_job_id,
                parent_id=v["parent_id"],
                phase_origin=origin,
                meta={"phase_key": phase_key},
            )
            created += 1
            existing_titles.add(v["title"].lower().strip())
            index_to_id[idx] = new_item.get("id", "")
            logger.info("EVOLVE: [%s] Created %s item %s: %s",
                        origin, v["item_type"], new_item.get("id"), v["title"][:60])
        except Exception as e:
            logger.warning("EVOLVE: [%s] Failed to create item '%s': %s",
                           origin, v["title"][:40], e)

    # --- Pass 2: proposals with "new:N" parent references ---
    for idx, finding in enumerate(findings):
        v = _validate_finding(finding)
        if not v:
            continue
        if v["action"] == "update":
            continue  # Already handled
        if not (v["parent_id"] and str(v["parent_id"]).startswith("new:")):
            continue  # Already handled in pass 1

        # Resolve "new:N" → actual ID
        try:
            ref_idx = int(str(v["parent_id"]).split(":", 1)[1])
            resolved_parent = index_to_id.get(ref_idx)
        except (ValueError, IndexError):
            resolved_parent = None

        if not resolved_parent:
            logger.warning("EVOLVE: [%s] Could not resolve parent ref '%s' for '%s' — creating without parent",
                           origin, v["parent_id"], v["title"][:40])

        # Dedup
        if v["title"].lower().strip() in existing_titles:
            skipped += 1
            continue

        try:
            new_item = await asyncio.to_thread(
                create_item,
                item_type=v["item_type"],
                title=v["title"],
                body=v["body"] or "",
                impact=v["impact"],
                effort=v["effort"],
                category=v["category"],
                created_by="skipper",
                cycle_id=cycle_id,
                cycle_job_id=cycle_job_id,
                parent_id=resolved_parent,
                phase_origin=origin,
                meta={"phase_key": phase_key},
            )
            created += 1
            existing_titles.add(v["title"].lower().strip())
            index_to_id[idx] = new_item.get("id", "")
            logger.info("EVOLVE: [%s] Created %s item %s: %s (parent: %s)",
                        origin, v["item_type"], new_item.get("id"),
                        v["title"][:60], resolved_parent or "none")
        except Exception as e:
            logger.warning("EVOLVE: [%s] Failed to create item '%s': %s",
                           origin, v["title"][:40], e)

    if created or updated or skipped:
        ctx.update_output(**{
            f"{origin}_items_created": created,
            f"{origin}_items_updated": updated,
            f"{origin}_items_skipped": skipped,
        })
        logger.info("EVOLVE: [%s] Created %d, updated %d, skipped %d",
                     origin, created, updated, skipped)


async def _handle_evolve_synthesis(job: dict, ctx: JobContext, config: dict) -> str:
    """Handle a synthesis unit — waits for siblings, then rolls up findings."""
    from data_layer.db import fetch_all
    from data_layer.job_queue import get_job

    parent_id = job.get("parent_job_id", "")
    job_id = job["id"]

    # Check if all sibling units are done
    siblings = fetch_all(
        "SELECT * FROM jobs WHERE parent_job_id = %s AND id != %s",
        (parent_id, job_id),
    )
    incomplete = [s for s in siblings if s["status"] not in ("completed", "failed")]
    if incomplete:
        # Not ready — raise RequeueRequested so dispatcher re-queues properly
        from job_dispatcher import RequeueRequested
        raise RequeueRequested(f"Waiting for {len(incomplete)} sibling units")

    ctx.update_progress(20, "All siblings complete — synthesizing...")

    # Gather all sibling outputs — keep full content for synthesis
    all_findings = []
    unit_outputs = []  # (unit_name, findings_list)
    total_tokens = 0
    for sib in siblings:
        output = sib.get("output") or {}
        if isinstance(output, str):
            import json as _json
            try:
                output = _json.loads(output)
            except Exception:
                output = {}
        findings = output.get("findings", [])
        all_findings.extend(findings)
        total_tokens += output.get("tokens_used", 0)
        if findings:
            unit_name = sib.get("name", sib.get("id", "unit"))
            unit_outputs.append((unit_name, findings))

    # Run synthesis LLM call
    import agent_loop
    import json as _json
    from config import SMART_MODEL

    phase = config.get("context", {}).get("phase", "unknown")
    synthesis_prompt = _load_evolve_prompt("synthesis")

    # Build user message with FULL finding content grouped by unit
    # The synthesis LLM needs the full details to extract distinct ideas
    unit_sections = []
    for unit_name, findings in unit_outputs:
        section = f"### Unit: {unit_name}\n"
        for f in findings[:10]:
            # Include full JSON so synthesis can see all fields
            section += _json.dumps(f, indent=2, default=str)[:2000] + "\n"
        unit_sections.append(section)

    user_parts = [
        f"Phase: {phase}",
        f"Total: {len(all_findings)} findings from {len(siblings)} analysis units.",
        "",
        "## Full Unit Outputs",
        "Read each unit's output carefully. Extract EVERY distinct idea as a separate finding.",
        "",
        "\n\n".join(unit_sections),
    ]

    # Include existing evolve items so synthesis can reference them for hierarchy
    try:
        from data_layer.db import fetch_all as _fa
        existing_items = _fa(
            "SELECT id, title, phase_origin, type, impact, category "
            "FROM evolution_items WHERE status NOT IN ('dismissed','rejected') "
            "ORDER BY created_at DESC LIMIT 200"
        )
        if existing_items:
            items_ctx = "\n".join(
                f"  - [{r['id']}] ({r.get('phase_origin','?')}/{r.get('type','?')}) "
                f"{r['title']}"
                for r in existing_items
            )
            user_parts.append(
                f"\n\n## Existing Evolve Items (reference by ID for parent_item_id):\n{items_ctx}"
            )

            # Include recent discussion threads so synthesis is aware of conversations
            from data_layer.evolution import get_thread as _get_thread
            discussed_items = [r for r in existing_items if r["id"]]
            discussion_sections = []
            for r in discussed_items[:50]:
                try:
                    thread = _get_thread(r["id"])
                    if thread and len(thread) >= 2:  # Only include items with real conversations
                        convo = "\n".join(
                            f"    {m['author']}: {m['body'][:300]}"
                            for m in thread[-6:]  # Last 6 messages
                        )
                        discussion_sections.append(
                            f"  [{r['id']}] {r['title']}:\n{convo}"
                        )
                except Exception:
                    pass
            if discussion_sections:
                user_parts.append(
                    f"\n\n## Active Discussions (Alice + Skipper conversations on items):\n"
                    + "\n\n".join(discussion_sections[:10])  # Cap at 10 discussions
                )
    except Exception as e:
        logger.debug("EVOLVE: Could not load existing items for synthesis context: %s", e)

    messages = [
        {"role": "system", "content": synthesis_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]

    tools, tool_dispatch = await _get_evolve_tools([])

    result = await agent_loop.run(
        messages=messages,
        tools=tools,
        model=SMART_MODEL,
        max_turns=3,
        tool_dispatch=tool_dispatch,
    )

    ctx.update_progress(90, "Saving synthesis to working memory...")

    # Save synthesis to working memory
    synthesis_output = _parse_evolve_output(result.response_text)
    try:
        from domain_evolve import _save_working_memory
        await _save_working_memory(phase, {
            "findings": synthesis_output,
            "summary": result.response_text or "",
            "unit_count": len(siblings),
            "total_tokens": total_tokens,
        })
    except Exception as e:
        logger.warning("EVOLVE: Could not save synthesis to working memory: %s", e)

    ctx.update_output(
        findings=synthesis_output,
        tokens_used=result.prompt_tokens + result.completion_tokens,
        synthesis=True,
        source_count=len(siblings),
    )

    # Create evolve items from synthesis findings (all phases, not just Phase 5)
    cycle_id = ""
    try:
        # Resolve cycle_job_id: phase parent = the cycle job
        phase_job = get_job(parent_id)
        cycle_job_id = (phase_job or {}).get("parent_job_id", "")
        cycle_id = config.get("cycle_id", "") or cycle_job_id
        phase_key = config.get("context", {}).get("phase_key", phase)
        await _create_items_from_synthesis(synthesis_output, phase_key, cycle_job_id, ctx,
                                           cycle_id=cycle_id)
    except Exception as e:
        logger.warning("EVOLVE: Could not create items from synthesis: %s", e)

    # Stack-rank all active items after each phase creates new ones
    try:
        await _prioritize_cycle_items(cycle_id, ctx)
    except Exception as e:
        logger.warning("EVOLVE: Prioritization failed (non-fatal): %s", e)

    return f"Synthesis complete: {len(synthesis_output)} items from {len(siblings)} units"


def _load_evolve_prompt(template_name: str) -> str:
    """Load a prompt template from prompts/evolve/{template_name}.md."""
    import os
    path = os.path.join("prompts", "evolve", f"{template_name}.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    # Fallback: minimal prompt
    return (
        "You are Skipper's self-improvement analysis engine. "
        "Analyze the provided context and return structured findings as JSON. "
        "Each finding should have: title, summary, impact (low/medium/high), "
        "effort (low/medium/high), category, and goal_link (if applicable)."
    )


def _build_evolve_user_message(template: str, context: dict) -> str:
    """Build the user message for an evolve unit from its context."""
    import json as _json
    parts = []
    for key, value in context.items():
        # Platform registry files: use full length + buffer (they grow over time)
        max_len = (len(value) + 3000) if key.startswith("PLATFORM_REGISTRY_") else 3000
        if isinstance(value, (dict, list)):
            parts.append(f"## {key}\n```json\n{_json.dumps(value, indent=2, default=str)[:max_len]}\n```")
        elif isinstance(value, str) and len(value) > 200:
            parts.append(f"## {key}\n{value[:max_len]}")
        else:
            parts.append(f"**{key}**: {value}")
    return "\n\n".join(parts) if parts else "No additional context provided."


def _parse_evolve_output(response: str | None) -> list[dict]:
    """Parse structured findings from an evolve unit's LLM response."""
    if not response:
        return []
    import json as _json
    # Try to extract JSON array from the response
    try:
        # Look for JSON block
        if "```json" in response:
            start = response.index("```json") + 7
            end = response.index("```", start)
            parsed = _json.loads(response[start:end])
        elif response.strip().startswith("["):
            parsed = _json.loads(response)
        elif response.strip().startswith("{"):
            parsed = _json.loads(response)
        else:
            parsed = None

        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            # Synthesis format: {"summary": "...", "findings": [...], ...}
            # Extract the inner findings array if present
            if "findings" in parsed and isinstance(parsed["findings"], list):
                return parsed["findings"]
            return [parsed]
    except (ValueError, _json.JSONDecodeError):
        pass
    # Fallback: treat the whole response as a single finding
    return [{"title": "Analysis result", "summary": response[:500], "raw": True}]


async def _get_evolve_tools(tool_names: list[str]) -> tuple:
    """Get OpenAI tool schemas and dispatcher for evolve units.

    Returns (tools_list, tool_dispatch_fn).
    If tool_names is empty, provides filesystem read tools only.
    """
    try:
        from mcp_client import get_openai_tools
        import tool_dispatch as _td
        # Get all tools, then filter if specific names requested
        all_tools = get_openai_tools()
        # Always include filesystem read tools
        read_tools = {"cat_file", "ls_dir", "grep_search",
                      "glob_search", "tail_file", "os_level_find"}
        # Merge with any extra tools requested by the unit
        allowed = read_tools | set(tool_names) if tool_names else read_tools
        tools = [t for t in all_tools
                 if t.get("function", {}).get("name") in allowed]

        async def dispatch(name, args):
            return await _td.call_tool(name, args)

        return tools, dispatch
    except Exception as e:
        logger.warning("EVOLVE: Could not load MCP tools: %s", e)
        return [], None


# ---------------------------------------------------------------------------
# Prioritization — stack-rank all active evolution items
# ---------------------------------------------------------------------------

async def _prioritize_cycle_items(cycle_id: str, ctx: JobContext):
    """Re-stack-rank all active evolution items using an LLM call.

    Called after each phase synthesis creates items, so the full set
    is always ranked relative to each other.
    """
    import asyncio
    import json as _json
    import agent_loop
    from config import SMART_MODEL
    from data_layer.db import fetch_all
    from data_layer.evolution import update_item

    # Load all active items (not dismissed/rejected/completed)
    items = await asyncio.to_thread(
        fetch_all,
        "SELECT id, type, title, body, impact, effort, category, parent_id, "
        "phase_origin, priority, priority_pin FROM evolution_items "
        "WHERE status NOT IN ('completed', 'dismissed', 'rejected') "
        "ORDER BY priority NULLS LAST, created_at",
    )
    if not items or len(items) < 2:
        return  # Nothing to rank

    # Separate goals and non-goals for two-list display
    goals = [it for it in items if it.get("type") == "goal"]
    proposals = [it for it in items if it.get("type") != "goal"]

    # Build id→title lookup for parent references
    id_to_title = {it["id"]: it["title"][:60] for it in items}

    def _fmt_item(it):
        parent = ""
        if it.get("parent_id"):
            ptitle = id_to_title.get(it["parent_id"], it["parent_id"])
            parent = f" (parent: {it['parent_id']} — {ptitle})"
        current = f" [current rank: {it['priority']}]" if it.get("priority") else ""
        pin = f" **PIN: {it['priority_pin']}**" if it.get("priority_pin") else ""
        return (
            f"- [{it['id']}] {it.get('type','?')}: {it['title']}  "
            f"impact={it.get('impact','?')} effort={it.get('effort','?')} "
            f"cat={it.get('category','?')}{parent}{current}{pin}"
        )

    goal_lines = [_fmt_item(g) for g in goals]
    proposal_lines = [_fmt_item(p) for p in proposals]

    # Load strategic directives from working memory
    directives_section = ""
    try:
        from domain_evolve import _load_working_memory
        wm = _load_working_memory()
        directives = wm.get("priority_directives")
        if directives:
            if isinstance(directives, dict):
                directives_text = directives.get("text", str(directives))
            else:
                directives_text = str(directives)
            directives_section = (
                f"\n\n## Strategic Directives from Alice\n{directives_text}"
            )
    except Exception as e:
        logger.debug("EVOLVE: Could not load priority directives: %s", e)

    prompt_text = _load_evolve_prompt("prioritize")

    user_content_parts = [
        f"## Goals ({len(goals)} items)\n",
        "\n".join(goal_lines) if goal_lines else "(none)",
        f"\n\n## Proposals / Findings / Work Items ({len(proposals)} items)\n",
        "\n".join(proposal_lines) if proposal_lines else "(none)",
    ]
    if directives_section:
        user_content_parts.append(directives_section)

    messages = [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": "\n".join(user_content_parts)},
    ]

    logger.info("EVOLVE: Prioritizing %d goals + %d proposals...",
                len(goals), len(proposals))

    result = await agent_loop.run(
        messages=messages,
        tools=[],
        model=SMART_MODEL,
        max_turns=1,
        tool_dispatch=None,
    )

    # Parse two-list output: {"goals": [...], "proposals": [...]}
    parsed = _parse_evolve_output(result.response_text)
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        parsed = parsed[0]  # _parse_evolve_output wraps single dicts in a list
    elif isinstance(parsed, list):
        # Fallback: if LLM returned a flat list, apply to all items
        parsed = {"goals": [], "proposals": parsed}

    if not isinstance(parsed, dict):
        logger.warning("EVOLVE: Prioritization returned unexpected format")
        return

    goal_rankings = parsed.get("goals", [])
    proposal_rankings = parsed.get("proposals", [])

    valid_ids = {it["id"] for it in items}
    updated = 0

    for entry in goal_rankings + proposal_rankings:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("id", "")
        rank = entry.get("rank")
        if item_id in valid_ids and isinstance(rank, int) and rank > 0:
            try:
                await asyncio.to_thread(update_item, item_id, priority=rank)
                updated += 1
            except Exception as e:
                logger.warning("EVOLVE: Failed to set priority on %s: %s", item_id, e)

    if updated:
        ctx.update_output(
            goals_prioritized=len([e for e in goal_rankings if isinstance(e, dict)]),
            proposals_prioritized=len([e for e in proposal_rankings if isinstance(e, dict)]),
        )
        logger.info("EVOLVE: Ranked %d goals + %d proposals (tokens: %d)",
                     len(goal_rankings), len(proposal_rankings),
                     result.prompt_tokens + result.completion_tokens)


# ---------------------------------------------------------------------------
# Meals — Dinner Check handler
# ---------------------------------------------------------------------------

def _handle_meals_dinner_check(job: dict, ctx: JobContext) -> str:
    """Check if tonight's dinner is logged; prompt Alice if not."""
    from apps.meals.handlers import handle_dinner_check
    return handle_dinner_check(job, ctx)


# ---------------------------------------------------------------------------
# Scriptures — nightly prefetch
# ---------------------------------------------------------------------------

def _handle_scripture_prefetch(job: dict, ctx: JobContext) -> str:
    """Pre-generate summary, people, and places for bookmarked chapters + 3 ahead."""
    from apps.scriptures.prefetch import prefetch_scripture_summaries
    return prefetch_scripture_summaries()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_all_handlers():
    """Register all job handlers with the dispatcher. Call once at startup."""
    register_handler("research", _handle_research, max_concurrent=2)
    register_handler("refine", _handle_refine, max_concurrent=2)
    register_handler("print", _handle_print, max_concurrent=1)
    register_handler("pm", _handle_pm, max_concurrent=1)
    register_handler("pm_check", _handle_pm_check, max_concurrent=1)
    register_handler("investment", _handle_investment, max_concurrent=1, cancel_on_shutdown=False)
    register_handler("rebalance", _handle_rebalance, max_concurrent=1, cancel_on_shutdown=False)
    register_handler("backup", _handle_backup, max_concurrent=1)
    register_handler("backup_check", _handle_backup_check, max_concurrent=1)
    register_handler("equity_curve", _handle_equity_curve, max_concurrent=1, cancel_on_shutdown=False)
    register_handler("folder_intelligence", _handle_folder_intelligence, max_concurrent=2)
    register_handler("evolve_unit", _handle_evolve_unit, max_concurrent=5)
    register_handler("meals_dinner_check", _handle_meals_dinner_check, max_concurrent=1)
    register_handler("scripture_prefetch", _handle_scripture_prefetch, max_concurrent=1)
    logger.info("JOB_HANDLERS: All handlers registered")
