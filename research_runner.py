"""Research Runner
=================
Background async pipeline that executes research jobs:
  1. Search the web (Brave API)
  2. Fetch top result pages
  3. Summarize each source with LLM
  4. Create a structured doc with all findings
  5. Notify the user on completion

Designed to run from the scheduler loop via asyncio.to_thread
so it doesn't block the event loop.
"""

import asyncio
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from config import logger, openai_client, SMART_MODEL, DUMB_MODEL, TIMEZONE

CENTRAL_TZ = ZoneInfo(TIMEZONE)

# Max chars of page text to send to the LLM for summarization
_MAX_PAGE_CHARS = 6000
# Timeout for individual HTTP fetches
_FETCH_TIMEOUT = 20


# ---------------------------------------------------------------------------
# HTML → plain text
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Strip HTML tags and extract readable text."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "head",
                    "nav", "header", "footer", "aside", "menu", "form"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        raw = "\n".join(self._parts)
        # Collapse runs of 3+ newlines and strip excessive whitespace
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text, stripping tags."""
    try:
        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        return extractor.get_text()
    except Exception:
        # Fallback: regex strip
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Web helpers (standalone, not importing tools to avoid circular deps)
# ---------------------------------------------------------------------------

def _brave_search(query: str, num_results: int = 5) -> list[dict]:
    """Search Brave API and return list of {title, url, snippet}.

    Retries up to 3 times with exponential backoff on 429 (rate limit) errors.
    """
    api_key = os.getenv("BRAVE_API_KEY", "")
    if not api_key:
        logger.error("RESEARCH: BRAVE_API_KEY not set")
        return []

    params = {
        "q": query,
        "count": str(min(num_results, 10)),
        "safesearch": "moderate",
        "text_decorations": "false",
    }
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(params)

    req_headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
        "User-Agent": "SkipperBot/1.0 (research_runner)",
    }

    max_retries = 3
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            results = (data.get("web") or {}).get("results") or []
            return [
                {
                    "title": (r.get("title") or "").strip(),
                    "url": (r.get("url") or "").strip(),
                    "snippet": (r.get("description") or "").strip(),
                }
                for r in results
                if r.get("url")
            ]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s
                logger.warning("RESEARCH: Brave 429 rate limit, retrying in %ds (attempt %d/%d)",
                               wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            logger.error("RESEARCH: Brave search failed: %s", e)
            return []
        except Exception as e:
            logger.error("RESEARCH: Brave search failed: %s", e)
            return []


def _fetch_page(url: str) -> str:
    """Fetch a URL and return plain text content."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "SkipperBot/1.0 (research_runner)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        })
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(2_000_000)  # cap at 2MB

        # Decode
        charset = "utf-8"
        m = re.search(r"charset=([^;]+)", content_type, re.IGNORECASE)
        if m:
            charset = m.group(1).strip()
        try:
            html = raw.decode(charset, errors="replace")
        except Exception:
            html = raw.decode("utf-8", errors="replace")

        text = _html_to_text(html)
        return text[:_MAX_PAGE_CHARS] if len(text) > _MAX_PAGE_CHARS else text

    except Exception as e:
        logger.warning("RESEARCH: Failed to fetch %s: %s", url, e)
        return ""


# ---------------------------------------------------------------------------
# LLM summarization
# ---------------------------------------------------------------------------

def _summarize_source(title: str, url: str, page_text: str, research_query: str) -> str:
    """Use LLM to summarize a single source relative to the research query."""
    if not page_text or len(page_text.strip()) < 50:
        return f"*Could not extract meaningful content from this page.*"

    try:
        resp = openai_client.chat.completions.create(
            model=DUMB_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant. Summarize the following web page content "
                        "as it relates to the research query. Extract key facts, data points, "
                        "and relevant information. Be concise but thorough. Use bullet points. "
                        "If the page is not relevant to the query, say so briefly."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Research query: {research_query}\n\n"
                        f"Page title: {title}\n"
                        f"URL: {url}\n\n"
                        f"Page content:\n{page_text[:_MAX_PAGE_CHARS]}"
                    ),
                },
            ],
            max_completion_tokens=4500,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("RESEARCH: LLM summarization failed for %s: %s", url, e)
        return f"*Summarization failed: {str(e)[:100]}*"


def _synthesize_doc(query: str, sources: list[dict],
                    spec_doc_content: str = "") -> str:
    """Use LLM to create a final structured research document from all source summaries."""
    sources_text = ""
    for i, s in enumerate(sources, 1):
        sources_text += (
            f"\n### Source {i}: {s['title']}\n"
            f"URL: {s['url']}\n"
            f"Summary:\n{s['summary']}\n"
        )

    # Build the user message with optional spec doc context
    user_parts = [f"# Research Query\n{query}"]
    if spec_doc_content:
        user_parts.append(
            f"# Specification Document (research requirements)\n"
            f"{spec_doc_content[:6000]}"
        )
    user_parts.append(f"# Source Summaries ({len(sources)} sources)\n{sources_text}")
    user_message = "\n\n".join(user_parts)

    try:
        resp = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert research analyst producing a comprehensive, "
                        "publication-quality research document. You have been given source "
                        "summaries from web research along with the original research query "
                        "and (optionally) a specification document describing output requirements.\n\n"
                        "Your job: synthesize ALL source material into a thorough, well-structured "
                        "markdown document. This is the final deliverable the user receives, so "
                        "quality and completeness are critical.\n\n"
                        "Default structure (override if the spec doc specifies a different format):\n"
                        "1. **Executive Summary** — concise overview of findings (2-3 paragraphs)\n"
                        "2. **Key Findings** — major takeaways organized by theme, with data points\n"
                        "3. **Detailed Analysis** — deeper exploration of each theme with evidence\n"
                        "4. **Sources** — numbered list of all sources with [title](url) and what each contributed\n"
                        "5. **Recommendations / Next Steps** — actionable conclusions\n\n"
                        "Rules:\n"
                        "- Be THOROUGH — include all relevant data, numbers, dates, and quotes from sources\n"
                        "- Cross-reference findings across sources where they agree or conflict\n"
                        "- Use markdown formatting: headers, bold, bullet points, tables where appropriate\n"
                        "- Cite sources inline using [Source N] notation\n"
                        "- If a spec doc is provided, follow its output format requirements exactly\n"
                        "- Write at least 1500-2000 words for 5+ sources\n"
                        "- Do NOT abbreviate, truncate, or produce stub sections\n"
                        "- If the research requires structured data output (e.g. JSON portfolio,\n"
                        "  data tables, config), put it in a fenced ```json code block at the END\n"
                        "  of the document. The system will automatically extract it into a\n"
                        "  separate data document. The JSON must be valid and self-contained."
                    ),
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            max_completion_tokens=16000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("RESEARCH: LLM synthesis failed: %s", e)
        # Fallback: just concatenate summaries
        fallback = f"# Research: {query}\n\n*Note: Automated synthesis failed. Raw summaries below.*\n"
        fallback += sources_text
        return fallback


# ---------------------------------------------------------------------------
# JSON extraction — split structured data out of synthesis output
# ---------------------------------------------------------------------------

def _extract_json_blocks(content: str) -> tuple[str, str]:
    """Extract JSON code blocks from synthesized content.

    Returns:
        (text_content, json_content) where:
        - text_content: the original content with JSON blocks removed
        - json_content: the extracted JSON (empty string if none found)

    Looks for ```json ... ``` fenced blocks. If multiple are found,
    they are combined into a single JSON document.
    """
    pattern = r"```json\s*\n(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL)

    if not matches:
        return content, ""

    # Validate that at least one block is parseable JSON
    valid_blocks = []
    for block in matches:
        block = block.strip()
        try:
            parsed = json.loads(block)
            # Pretty-print for the data doc
            valid_blocks.append(json.dumps(parsed, indent=2))
        except (json.JSONDecodeError, ValueError):
            logger.warning("RESEARCH: Found JSON code fence but content is not valid JSON")
            continue

    if not valid_blocks:
        return content, ""

    # Remove JSON blocks from the text content
    text_content = re.sub(pattern, "", content, flags=re.DOTALL).strip()
    # Clean up any leftover double blank lines
    text_content = re.sub(r"\n{3,}", "\n\n", text_content)

    # Combine valid blocks (usually just one)
    if len(valid_blocks) == 1:
        json_content = valid_blocks[0]
    else:
        json_content = json.dumps(
            [json.loads(b) for b in valid_blocks], indent=2
        )

    return text_content, json_content


# ---------------------------------------------------------------------------
# Research planner — intelligent query planning for any research job
# ---------------------------------------------------------------------------

_MAX_BRAVE_QUERY_LEN = 200  # Brave API rejects very long queries (422)


def _plan_research(query: str, num_sources: int,
                   spec_doc_content: str = "") -> dict:
    """Plan a research job by generating strategic search queries.

    Uses the SMART model to analyze the research request (and optional
    specification document) and produce a structured plan with targeted
    search queries optimized for web search engines.

    Args:
        query: The research prompt / topic from the user or LLM.
        num_sources: How many total sources the job should collect.
        spec_doc_content: Optional document content that serves as
                         detailed research specifications.

    Returns:
        dict with keys:
            queries: list[str]  — search queries to execute
            strategy: str       — brief description of the research strategy
            focus_areas: list[str] — key topics/angles being covered
    """
    # Number of distinct queries scales with source count
    num_queries = max(2, min(num_sources, 4))

    # Build the context block for the planner
    context_parts = [f"## Research Request\n{query}"]
    if spec_doc_content:
        # Cap spec doc to avoid blowing up context
        trimmed = spec_doc_content[:8000]
        context_parts.append(f"## Specification Document\n{trimmed}")

    context_block = "\n\n".join(context_parts)

    try:
        resp = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert research planner. Your job is to analyze a research "
                        "request (and optional specification document) and produce a strategic "
                        "set of web search queries that will yield the best results.\n\n"
                        "Think carefully about:\n"
                        "- What specific data, facts, or perspectives the research needs\n"
                        "- Which authoritative sources are likely to have this information\n"
                        "- How to phrase queries to find current, high-quality results\n"
                        "- Covering different angles to get a complete picture\n"
                        "- Avoiding redundant queries that would return the same pages\n\n"
                        "Rules:\n"
                        f"- Generate exactly {num_queries} search queries\n"
                        "- Each query MUST be under 120 characters (web search engine limit)\n"
                        "- Use natural search language — no boolean operators\n"
                        "- Include the current year (2026) where freshness matters\n"
                        "- Target specific data sources when relevant (e.g. 'Fed dot plot',\n"
                        "  'BLS CPI report', 'IMF World Economic Outlook')\n"
                        "- Vary query specificity: mix broad landscape queries with\n"
                        "  narrow data-point queries\n\n"
                        "Respond with ONLY valid JSON matching this schema:\n"
                        "{\n"
                        '  "strategy": "Brief description of research approach",\n'
                        '  "focus_areas": ["area1", "area2", ...],\n'
                        '  "queries": ["search query 1", "search query 2", ...]\n'
                        "}"
                    ),
                },
                {
                    "role": "user",
                    "content": context_block,
                },
            ],
            max_completion_tokens=2000,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        plan = json.loads(raw)

        # Validate and extract
        queries = plan.get("queries", [])
        if not isinstance(queries, list) or not queries:
            raise ValueError("Planner returned no queries")

        return {
            "queries": [str(q).strip() for q in queries[:num_queries] if q],
            "strategy": str(plan.get("strategy", "")),
            "focus_areas": [str(a) for a in plan.get("focus_areas", [])],
        }

    except Exception as e:
        logger.warning("RESEARCH: Planner failed, falling back to simple decomposition: %s", e)

    # Fallback: if the query is short enough, use directly; otherwise truncate
    if len(query) <= _MAX_BRAVE_QUERY_LEN:
        return {"queries": [query], "strategy": "direct query (planner fallback)",
                "focus_areas": []}
    return {"queries": [query[:_MAX_BRAVE_QUERY_LEN]],
            "strategy": "truncated query (planner fallback)", "focus_areas": []}


# ---------------------------------------------------------------------------
# Main pipeline (runs in thread via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _run_research_pipeline(job: dict) -> dict:
    """Execute the full research pipeline synchronously.

    Returns dict with: success (bool), doc_id, sources_found, sources_read, error.
    """
    from job_store import update_job_progress, get_job
    from doc_store import create_doc, update_doc
    from app_platform.notifications import create_notification

    job_id = job["id"]
    config = job.get("config", {})
    query = config.get("query", "")
    num_sources = config.get("num_sources", 5)
    related_entity_id = config.get("related_entity_id", "")
    tags = config.get("tags", [])
    notify_user = job.get("notify_user", job.get("created_by", ""))
    created_by = job.get("created_by", "system")

    result = {
        "success": False,
        "doc_id": "",
        "sources_found": 0,
        "sources_read": 0,
        "error": "",
    }

    try:
        # --- Step 0: Load spec doc if provided ---
        spec_doc_id = config.get("spec_doc_id", "")
        spec_doc_content = ""
        if spec_doc_id:
            update_job_progress(job_id, f"Loading specification doc {spec_doc_id}...", status="running")
            try:
                from doc_store import get_doc
                spec_doc = get_doc(spec_doc_id)
                if spec_doc and spec_doc.get("content"):
                    spec_doc_content = spec_doc["content"]
                    logger.info("RESEARCH [%s]: Loaded spec doc %s (%d chars)",
                                job_id, spec_doc_id, len(spec_doc_content))
                else:
                    logger.warning("RESEARCH [%s]: Spec doc %s not found or empty", job_id, spec_doc_id)
            except Exception as e:
                logger.warning("RESEARCH [%s]: Failed to load spec doc %s: %s", job_id, spec_doc_id, e)

        # --- Step 1: Plan research + Search ---
        update_job_progress(job_id, f"Planning research strategy...", status="running")
        plan = _plan_research(query, num_sources, spec_doc_content=spec_doc_content)
        queries = plan["queries"]
        logger.info("RESEARCH [%s]: Strategy: %s", job_id, plan.get("strategy", ""))
        logger.info("RESEARCH [%s]: Focus areas: %s", job_id, plan.get("focus_areas", []))
        logger.info("RESEARCH [%s]: Planned %d queries: %s", job_id, len(queries), queries)

        update_job_progress(job_id, f"Searching web ({len(queries)} queries)...")
        search_results = []
        seen_urls: set[str] = set()

        for qi, q in enumerate(queries):
            # Rate-limit: pause between Brave API calls to avoid 429
            if qi > 0:
                time.sleep(10)

            # Distribute sources across queries
            per_query = max(1, num_sources // len(queries))
            if qi == len(queries) - 1:
                per_query = num_sources - len(search_results)
            if per_query <= 0:
                break

            hits = _brave_search(q, num_results=per_query + 2)  # fetch extra to dedupe
            for sr in hits:
                if sr["url"] not in seen_urls and len(search_results) < num_sources:
                    seen_urls.add(sr["url"])
                    search_results.append(sr)

        if not search_results:
            result["error"] = "No search results found"
            update_job_progress(job_id, "Failed: no search results", status="failed")
            return result

        result["sources_found"] = len(search_results)
        update_job_progress(
            job_id,
            f"Found {len(search_results)} sources. Fetching pages...",
            output_updates={"sources_found": len(search_results)},
        )

        # Check cancellation
        fresh = get_job(job_id)
        if fresh and fresh.get("cancelled"):
            result["error"] = "Cancelled"
            return result

        # --- Step 2: Fetch and summarize each source ---
        processed_sources = []
        for i, sr in enumerate(search_results):
            # Check cancellation between sources
            fresh = get_job(job_id)
            if fresh and fresh.get("cancelled"):
                result["error"] = "Cancelled"
                return result

            update_job_progress(
                job_id,
                f"Reading source {i + 1}/{len(search_results)}: {sr['title'][:50]}...",
            )

            page_text = _fetch_page(sr["url"])
            if page_text:
                result["sources_read"] += 1

            summary = _summarize_source(sr["title"], sr["url"], page_text, query)
            logger.info("RESEARCH [%s]: Source %d summary: %d chars, content: %d chars",
                        job_id, i + 1, len(summary), len(page_text) if page_text else 0)
            processed_sources.append({
                "title": sr["title"],
                "url": sr["url"],
                "snippet": sr["snippet"],
                "summary": summary,
                "had_content": bool(page_text),
            })

            update_job_progress(
                job_id,
                f"Summarized {i + 1}/{len(search_results)} sources",
                output_updates={"sources_read": result["sources_read"]},
            )

        # Check cancellation before synthesis
        fresh = get_job(job_id)
        if fresh and fresh.get("cancelled"):
            result["error"] = "Cancelled"
            return result

        # --- Step 3: Synthesize into document ---
        update_job_progress(job_id, "Synthesizing findings into document...")

        doc_content = _synthesize_doc(query, processed_sources,
                                         spec_doc_content=spec_doc_content)
        logger.info("RESEARCH [%s]: Synthesis produced %d chars / ~%d words",
                    job_id, len(doc_content), len(doc_content.split()))

        # Prepend a header with metadata
        spec_note = f" | Spec doc: {spec_doc_id}" if spec_doc_id else ""
        strategy_note = ""
        if plan.get("strategy") and plan["strategy"] != "direct query (planner fallback)":
            strategy_note = f"\n> *Strategy: {plan['strategy']}*\n"
        header = (
            f"# Research: {query}\n\n"
            f"> *Automated research by SkipperBot | "
            f"{datetime.now(CENTRAL_TZ).strftime('%B %d, %Y at %I:%M %p')} CT | "
            f"{result['sources_read']}/{result['sources_found']} sources read"
            f"{spec_note}*\n{strategy_note}\n"
        )
        full_content = header + doc_content

        # --- Step 4: Create document(s) ---
        update_job_progress(job_id, "Creating research document...")

        # Extract JSON data blocks from synthesis (if any)
        text_content, json_content = _extract_json_blocks(doc_content)
        if json_content:
            logger.info("RESEARCH [%s]: Extracted %d chars of JSON data into separate doc",
                        job_id, len(json_content))
            # Use the cleaned text (JSON removed) for the findings doc
            full_content = header + text_content
        # else full_content already includes everything

        research_tags = list(set(["research"] + tags))

        # Create the findings document (text report)
        short_title = query[:80] if len(query) <= 80 else query[:77] + "..."
        doc = create_doc(
            title=f"Research: {short_title}",
            created_by=created_by,
            content=full_content,
            tags=research_tags,
            related_entity_id=related_entity_id,
        )
        result["doc_id"] = doc["id"]
        result["full_content"] = full_content
        result["word_count"] = doc.get("word_count", 0)
        result["success"] = True

        # Create the JSON data document (if structured data was found)
        data_doc_id = ""
        if json_content:
            data_tags = list(set(["research", "data", "json"] + tags))
            data_doc = create_doc(
                title=f"Research Data: {short_title}",
                created_by=created_by,
                content=json_content,
                tags=data_tags,
                related_entity_id=related_entity_id,
            )
            data_doc_id = data_doc["id"]
            result["data_doc_id"] = data_doc_id
            logger.info("RESEARCH [%s]: Created data doc %s (%d chars JSON)",
                        job_id, data_doc_id, len(json_content))

        # Update progress
        docs_msg = f"Document: {doc['id']} ({doc.get('word_count', 0)} words)"
        if data_doc_id:
            docs_msg += f" + Data: {data_doc_id}"
        update_job_progress(
            job_id,
            f"Complete! {docs_msg}",
            status="completed",
            output_updates={"doc_id": doc["id"], "data_doc_id": data_doc_id},
        )

        logger.info("RESEARCH [%s]: Completed. Doc: %s, Data: %s (%d sources)",
                     job_id, doc["id"], data_doc_id or "(none)", result["sources_read"])

        # --- Step 5: Notify ---
        try:
            notify_lines = [
                f"Research complete: \"{query[:60]}\"",
                f"Findings: {doc['id']} ({doc.get('word_count', 0)} words, "
                f"{result['sources_read']} sources)",
            ]
            if data_doc_id:
                notify_lines.append(f"Data (JSON): {data_doc_id}")
            notify_lines.append(f"Use `get_doc {doc['id']}` to read the report.")

            create_notification(
                recipient=notify_user,
                message="\n".join(notify_lines),
                source_type="research",
                source_id=job_id,
                channel="discord",
                delivered=False,  # will be delivered by _deliver_research_notification
            )
        except Exception as e:
            logger.error("RESEARCH [%s]: Failed to create notification: %s", job_id, e)

        return result

    except Exception as e:
        result["error"] = str(e)
        logger.error("RESEARCH [%s]: Pipeline failed: %s", job_id, e, exc_info=True)
        update_job_progress(job_id, f"Failed: {str(e)[:200]}", status="failed")
        return result


# ---------------------------------------------------------------------------
# Notification delivery (async, uses Discord bot)
# ---------------------------------------------------------------------------

async def _deliver_research_notification(job: dict, result: dict):
    """Send completion notification via Discord DM + Pushover.

    Discord gets the FULL document content (send_dm auto-chunks at 2000 chars).
    Pushover gets a short alert.
    Chat history gets the full content so the agent has context.
    """
    notify_user = job.get("notify_user", job.get("created_by", ""))
    query = job.get("config", {}).get("query", "?")
    job_id = job["id"]

    if result.get("success"):
        doc_id = result.get("doc_id", "?")
        data_doc_id = result.get("data_doc_id", "")
        word_count = result.get("word_count", 0)
        sources_read = result.get("sources_read", 0)
        full_content = result.get("full_content", "")

        # Full message for Discord: header + entire doc content
        data_line = f"\nData (JSON): {data_doc_id}" if data_doc_id else ""
        header = (
            f"📋 Research complete: \"{query[:80]}\""
            f"\nFindings: {doc_id} ({word_count} words, {sources_read} sources)"
            f"{data_line}"
            f"\n---\n"
        )
        discord_msg = header + full_content if full_content else header + "(content unavailable — use get_doc to read)"

        # Short alert for Pushover
        data_short = f" | Data: {data_doc_id}" if data_doc_id else ""
        pushover_msg = (
            f"Research complete: \"{query[:60]}\""
            f"\n{word_count} words, {sources_read} sources. Doc: {doc_id}{data_short}"
        )
    elif result.get("error") == "Cancelled":
        discord_msg = f"🚫 Research cancelled: \"{query[:60]}\""
        pushover_msg = discord_msg
    else:
        discord_msg = f"❌ Research failed: \"{query[:60]}\"\nError: {result.get('error', 'unknown')[:200]}"
        pushover_msg = discord_msg

    # Discord DM — sends full content, auto-chunked at 2000 chars
    try:
        from discord_bot import send_dm
        await send_dm(notify_user, discord_msg)
        logger.info("RESEARCH [%s]: Discord notification sent to %s (%d chars)",
                     job_id, notify_user, len(discord_msg))
    except Exception as e:
        logger.error("RESEARCH [%s]: Discord notification failed: %s", job_id, e)

    # Pushover (configured users only) — short alert only
    try:
        from tools.pushover_tool import is_pushover_user, send_pushover_notification
        if is_pushover_user(notify_user):
            from discord_bot import strip_entity_ids
            send_pushover_notification(
                notify_user,
                strip_entity_ids(pushover_msg),
                cooldown_seconds=0,
            )
            logger.info("RESEARCH [%s]: Pushover notification sent to %s", job_id, notify_user)
    except Exception as e:
        logger.error("RESEARCH [%s]: Pushover notification failed: %s", job_id, e)

    # WebSocket — push to web UI if user is connected
    try:
        from connections import manager
        await manager.send_to_user(notify_user, {
            "type": "notification",
            "source": "research",
            "message": discord_msg,
            "user_id": notify_user,
        })

        # Auto-open output documents as new tabs in the web desktop
        if result.get("success"):
            doc_id = result.get("doc_id", "")
            data_doc_id = result.get("data_doc_id", "")
            if doc_id:
                await manager.send_to_user(notify_user, {
                    "type": "open_app",
                    "app_type": "documents",
                    "context": {"doc_id": doc_id, "title": f"Research: {query[:60]}"},
                })
                logger.info("RESEARCH [%s]: Opened findings doc %s in web desktop", job_id, doc_id)
            if data_doc_id:
                await manager.send_to_user(notify_user, {
                    "type": "open_app",
                    "app_type": "documents",
                    "context": {"doc_id": data_doc_id, "title": f"Research Data: {query[:50]}"},
                })
                logger.info("RESEARCH [%s]: Opened data doc %s in web desktop", job_id, data_doc_id)
    except Exception as e:
        logger.error("RESEARCH [%s]: WebSocket notification failed: %s", job_id, e)

    # Log full content to chat history so the agent has context
    try:
        from chatlog_store import save_notification
        save_notification(notify_user, discord_msg, context="research_notification")
    except Exception as e:
        logger.error("RESEARCH [%s]: Failed to log to chat history: %s", job_id, e)


# ---------------------------------------------------------------------------
# Refinement pipeline — iterative research on existing documents
# ---------------------------------------------------------------------------

def _generate_refine_queries(original_content: str, instructions: str, num_queries: int = 3) -> list[str]:
    """Use LLM to generate focused search queries for refining a document.

    Reads the original document and the user's refinement instructions,
    then produces targeted search queries to find additional information.
    """
    try:
        resp = openai_client.chat.completions.create(
            model=DUMB_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant. Given an existing research document and "
                        "instructions about what to expand or improve, generate focused web search "
                        "queries to find the additional information needed.\n\n"
                        "Rules:\n"
                        "- Generate exactly the requested number of search queries\n"
                        "- Each query should be specific and targeted to the refinement request\n"
                        "- Queries should complement (not repeat) what the document already covers\n"
                        "- Use natural search language, not boolean operators\n\n"
                        "Respond with a JSON array of query strings. Example:\n"
                        '[\"best vacuum bell brands for pectus excavatum 2026\", '
                        '\"vacuum bell therapy duration and results studies\"]'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Refinement Instructions:\n{instructions}\n\n"
                        f"## Existing Document (first 3000 chars):\n{original_content[:3000]}"
                    ),
                },
            ],
            max_completion_tokens=1000,
        )
        raw = resp.choices[0].message.content.strip()
        # Parse the JSON array of queries
        queries = json.loads(raw)
        if isinstance(queries, list):
            return [str(q).strip() for q in queries[:num_queries] if q]
        return [instructions]  # fallback
    except Exception as e:
        logger.warning("REFINE: Failed to generate queries, using instructions as query: %s", e)
        return [instructions]


def _split_into_sections(content: str) -> list[dict]:
    """Split a markdown document into sections by headings.

    Returns list of dicts: {"heading": str, "level": int, "body": str, "index": int}.
    A preamble before the first heading gets heading="" and level=0.
    """
    lines = content.split("\n")
    sections = []
    current: dict = {"heading": "", "level": 0, "lines": [], "index": 0}

    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            # Save previous section
            current["body"] = "\n".join(current.pop("lines"))
            sections.append(current)
            current = {
                "heading": m.group(2).strip(),
                "level": len(m.group(1)),
                "lines": [line],
                "index": len(sections),
            }
        else:
            current["lines"].append(line)

    # Save last section
    current["body"] = "\n".join(current.pop("lines"))
    sections.append(current)

    return sections


def _reassemble_sections(sections: list[dict]) -> str:
    """Reassemble sections back into a markdown document."""
    return "\n".join(s["body"] for s in sections)


def _format_sources_text(sources: list[dict]) -> str:
    """Format source summaries into text for LLM prompts."""
    parts = []
    for i, s in enumerate(sources, 1):
        parts.append(
            f"\n### New Source {i}: {s['title']}\n"
            f"URL: {s['url']}\n"
            f"Summary:\n{s['summary']}\n"
        )
    return "".join(parts)


def _identify_target_sections(
    sections: list[dict], instructions: str, sources_summary: str,
) -> dict:
    """Use LLM to decide which sections to revise, and whether to add new ones.

    Returns dict with:
        - "revise": list of section indices to revise
        - "new_sections": list of {"heading": str, "after_index": int} for new sections
    """
    section_index = ""
    for s in sections:
        if s["heading"]:
            prefix = "#" * s["level"]
            word_count = len(s["body"].split())
            section_index += f"  [{s['index']}] {prefix} {s['heading']} ({word_count} words)\n"

    try:
        resp = openai_client.chat.completions.create(
            model=DUMB_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research editor planning revisions to a document. "
                        "Given the document's section outline, refinement instructions, and a "
                        "summary of new source material, decide which sections need to be revised "
                        "and whether any new sections should be added.\n\n"
                        "Respond with a JSON object:\n"
                        "{\n"
                        '  "revise": [1, 3, 5],  // section indices to revise\n'
                        '  "new_sections": [\n'
                        '    {"heading": "New Section Title", "after_index": 4}\n'
                        "  ]  // new sections to add (empty array if none needed)\n"
                        "}\n\n"
                        "Rules:\n"
                        "- Only mark sections for revision if the instructions + new sources are relevant to them\n"
                        "- Always include the Sources section (if it exists) when adding new sources\n"
                        "- Prefer expanding existing sections over creating new ones\n"
                        "- Keep the list minimal — don't revise sections that don't need changes"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Refinement Instructions:\n{instructions}\n\n"
                        f"## New Source Material (summary):\n{sources_summary[:2000]}\n\n"
                        f"## Document Sections:\n{section_index}"
                    ),
                },
            ],
            max_completion_tokens=1000,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        plan = json.loads(raw)
        return {
            "revise": [int(i) for i in plan.get("revise", [])],
            "new_sections": plan.get("new_sections", []),
        }
    except Exception as e:
        logger.warning("REFINE: Failed to plan revisions, will revise all content sections: %s", e)
        # Fallback: revise all non-preamble sections
        return {
            "revise": [s["index"] for s in sections if s["heading"]],
            "new_sections": [],
        }


def _revise_section(
    section_body: str, section_heading: str,
    instructions: str, sources_text: str,
) -> str:
    """Revise a single section with new findings.

    Only this section's content is regenerated — all other sections stay untouched.
    """
    try:
        resp = openai_client.chat.completions.create(
            model=DUMB_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant revising ONE SECTION of a research document. "
                        "You will receive the section's current content and new source material.\n\n"
                        "Rules:\n"
                        "- Output ONLY the revised section content (including the heading line)\n"
                        "- Preserve existing content and integrate new findings naturally\n"
                        "- Expand the section based on the refinement instructions\n"
                        "- If this is the Sources section, add new sources to the list\n"
                        "- Mark expanded areas with a subtle *(expanded)* note\n"
                        "- Keep markdown formatting consistent\n"
                        "- Do NOT add content that belongs in other sections\n"
                        "- Do NOT output anything outside of this single section"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Refinement Instructions:\n{instructions}\n\n"
                        f"## New Source Material:\n{sources_text}\n\n"
                        f"## Current Section to Revise:\n{section_body}"
                    ),
                },
            ],
            max_completion_tokens=4000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("REFINE: Failed to revise section '%s': %s", section_heading, e)
        return section_body  # return unchanged on failure


def _create_new_section(heading: str, instructions: str, sources_text: str) -> str:
    """Generate a brand-new section to be inserted into the document."""
    try:
        resp = openai_client.chat.completions.create(
            model=DUMB_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant writing a NEW section for a research document. "
                        "Write a well-structured section using the provided source material.\n\n"
                        "Rules:\n"
                        "- Start with the heading line (## level)\n"
                        "- Use markdown formatting (bullet points, bold, etc.)\n"
                        "- Be thorough but concise\n"
                        "- Only include information from the provided sources\n"
                        "- Mark the section with *(new section)* after the heading"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Section to write: {heading}\n\n"
                        f"## Context/Instructions:\n{instructions}\n\n"
                        f"## Source Material:\n{sources_text}"
                    ),
                },
            ],
            max_completion_tokens=3000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("REFINE: Failed to create new section '%s': %s", heading, e)
        return f"## {heading}\n\n*Section generation failed. Source material is available in the refinement job.*\n"


def _revise_doc(original_content: str, instructions: str, new_sources: list[dict]) -> str:
    """Section-aware document revision.

    Instead of regenerating the entire document in one pass, this:
    1. Splits the document into sections by markdown headings
    2. Uses LLM to identify which sections need revision
    3. Revises only those sections individually (each with a focused output budget)
    4. Optionally adds new sections where needed
    5. Stitches everything back together

    This scales to documents of any size — unchanged sections pass through untouched,
    and each revised section gets its own focused LLM call.
    """
    sources_text = _format_sources_text(new_sources)

    # Build a short summary of new sources for the planning step
    sources_summary = "\n".join(
        f"- {s['title']}: {s['summary'][:150]}..." for s in new_sources
    )

    # Split into sections
    sections = _split_into_sections(original_content)
    if len(sections) <= 1:
        # Document has no headings — fall back to single-pass for very short docs
        return _revise_section(original_content, "", instructions, sources_text)

    logger.info("REFINE: Document has %d sections. Planning targeted revisions...", len(sections))

    # Identify which sections to revise
    plan = _identify_target_sections(sections, instructions, sources_summary)
    revise_indices = set(plan.get("revise", []))
    new_section_specs = plan.get("new_sections", [])

    logger.info("REFINE: Plan — revise %d sections, add %d new sections",
                 len(revise_indices), len(new_section_specs))

    # Revise targeted sections
    for idx in revise_indices:
        if 0 <= idx < len(sections):
            s = sections[idx]
            logger.info("REFINE: Revising section [%d] '%s' (%d words)",
                         idx, s["heading"][:40], len(s["body"].split()))
            revised = _revise_section(s["body"], s["heading"], instructions, sources_text)
            sections[idx]["body"] = revised

    # Insert new sections (process in reverse order to preserve indices)
    for spec in sorted(new_section_specs, key=lambda x: x.get("after_index", 999), reverse=True):
        heading = spec.get("heading", "Additional Information")
        after_idx = spec.get("after_index", len(sections) - 1)
        logger.info("REFINE: Creating new section '%s' after index %d", heading, after_idx)
        new_body = _create_new_section(heading, instructions, sources_text)
        new_section = {"heading": heading, "level": 2, "body": new_body, "index": -1}
        sections.insert(after_idx + 1, new_section)

    return _reassemble_sections(sections)


def _run_refine_pipeline(job: dict) -> dict:
    """Execute the refinement pipeline synchronously.

    1. Load original document
    2. Generate focused search queries from doc + instructions
    3. Search, fetch, summarize new sources
    4. Revise the document with new findings
    5. Create a new versioned document (original stays untouched)
    6. Notify user

    Returns dict with: success, doc_id, parent_doc_id, sources_read, error, full_content.
    """
    from job_store import update_job_progress, get_job
    from doc_store import create_doc, get_doc
    from app_platform.notifications import create_notification

    job_id = job["id"]
    config = job.get("config", {})
    doc_id = config.get("doc_id", "")
    instructions = config.get("instructions", "")
    num_sources = config.get("num_sources", 3)
    notify_user = job.get("notify_user", job.get("created_by", ""))
    created_by = job.get("created_by", "system")

    result = {
        "success": False,
        "doc_id": "",
        "parent_doc_id": doc_id,
        "sources_found": 0,
        "sources_read": 0,
        "error": "",
    }

    try:
        # --- Step 1: Load original document ---
        update_job_progress(job_id, f"Loading original document {doc_id}...", status="running")

        original = get_doc(doc_id)
        if not original:
            result["error"] = f"Document {doc_id} not found"
            update_job_progress(job_id, result["error"], status="failed")
            return result

        original_content = original.get("content", "")
        original_title = original.get("title", "Research")
        original_tags = original.get("tags", [])
        original_related = original.get("related_entity_id", "")
        original_version = original.get("version", 1)

        if not original_content.strip():
            result["error"] = f"Document {doc_id} has no content to refine"
            update_job_progress(job_id, result["error"], status="failed")
            return result

        # Check cancellation
        fresh = get_job(job_id)
        if fresh and fresh.get("cancelled"):
            result["error"] = "Cancelled"
            return result

        # --- Step 2: Generate focused search queries ---
        update_job_progress(job_id, "Generating targeted search queries...")

        num_queries = min(num_sources, 3)  # 1-3 distinct queries
        queries = _generate_refine_queries(original_content, instructions, num_queries)
        logger.info("REFINE [%s]: Generated %d queries: %s", job_id, len(queries), queries)

        # --- Step 3: Search, fetch, and summarize ---
        all_search_results = []
        seen_urls = set()

        for qi, query in enumerate(queries):
            # Rate-limit: pause between Brave API calls to avoid 429
            if qi > 0:
                time.sleep(10)

            fresh = get_job(job_id)
            if fresh and fresh.get("cancelled"):
                result["error"] = "Cancelled"
                return result

            update_job_progress(job_id, f"Searching ({qi + 1}/{len(queries)}): {query[:50]}...")

            per_query = max(1, num_sources // len(queries))
            if qi == len(queries) - 1:
                # Last query gets any remainder
                per_query = num_sources - len(all_search_results)
            if per_query <= 0:
                break

            search_results = _brave_search(query, num_results=per_query + 2)  # fetch extra to dedupe
            for sr in search_results:
                if sr["url"] not in seen_urls and len(all_search_results) < num_sources:
                    seen_urls.add(sr["url"])
                    all_search_results.append(sr)

        result["sources_found"] = len(all_search_results)

        if not all_search_results:
            result["error"] = "No search results found for refinement queries"
            update_job_progress(job_id, result["error"], status="failed")
            return result

        update_job_progress(
            job_id,
            f"Found {len(all_search_results)} new sources. Fetching...",
            output_updates={"sources_found": len(all_search_results)},
        )

        processed_sources = []
        for i, sr in enumerate(all_search_results):
            fresh = get_job(job_id)
            if fresh and fresh.get("cancelled"):
                result["error"] = "Cancelled"
                return result

            update_job_progress(
                job_id,
                f"Reading new source {i + 1}/{len(all_search_results)}: {sr['title'][:50]}...",
            )

            page_text = _fetch_page(sr["url"])
            if page_text:
                result["sources_read"] += 1

            # Summarize relative to the refinement instructions (not original query)
            summary = _summarize_source(sr["title"], sr["url"], page_text, instructions)
            processed_sources.append({
                "title": sr["title"],
                "url": sr["url"],
                "snippet": sr["snippet"],
                "summary": summary,
                "had_content": bool(page_text),
            })

            update_job_progress(
                job_id,
                f"Summarized {i + 1}/{len(all_search_results)} new sources",
                output_updates={"sources_read": result["sources_read"]},
            )

        # Check cancellation before revision
        fresh = get_job(job_id)
        if fresh and fresh.get("cancelled"):
            result["error"] = "Cancelled"
            return result

        # --- Step 4: Revise the document ---
        update_job_progress(job_id, "Revising document with new findings...")

        revised_content = _revise_doc(original_content, instructions, processed_sources)

        # Prepend a version header
        new_version = original_version + 1
        header = (
            f"# {original_title} (v{new_version})\n\n"
            f"> *Revised by SkipperBot | "
            f"{datetime.now(CENTRAL_TZ).strftime('%B %d, %Y at %I:%M %p')} CT | "
            f"Based on {doc_id} | "
            f"{result['sources_read']} additional sources*\n\n"
            f"> *Refinement: {instructions[:200]}*\n\n"
        )
        full_content = header + revised_content

        # --- Step 5: Create the revised doc ---
        update_job_progress(job_id, "Creating revised document...")

        revision_tags = list(set(original_tags + ["revision"]))
        new_doc = create_doc(
            title=f"{original_title} (v{new_version})",
            created_by=created_by,
            content=full_content,
            tags=revision_tags,
            related_entity_id=original_related,
            parent_doc_id=doc_id,
            version=new_version,
        )
        result["doc_id"] = new_doc["id"]
        result["full_content"] = full_content
        result["word_count"] = new_doc.get("word_count", 0)
        result["version"] = new_version
        result["success"] = True

        update_job_progress(
            job_id,
            f"Complete! Revised document: {new_doc['id']} (v{new_version}, "
            f"{new_doc.get('word_count', 0)} words)",
            status="completed",
            output_updates={"doc_id": new_doc["id"], "parent_doc_id": doc_id},
        )

        logger.info("REFINE [%s]: Completed. New doc: %s (v%d, from %s, %d new sources)",
                     job_id, new_doc["id"], new_version, doc_id, result["sources_read"])

        # Notification record
        try:
            create_notification(
                recipient=notify_user,
                message=(
                    f"Research refinement complete: {doc_id} → {new_doc['id']} (v{new_version})\n"
                    f"Instructions: {instructions[:100]}\n"
                    f"{result['sources_read']} additional sources"
                ),
                source_type="refine",
                source_id=job_id,
                channel="discord",
                delivered=False,
            )
        except Exception as e:
            logger.error("REFINE [%s]: Failed to create notification: %s", job_id, e)

        return result

    except Exception as e:
        result["error"] = str(e)
        logger.error("REFINE [%s]: Pipeline failed: %s", job_id, e, exc_info=True)
        update_job_progress(job_id, f"Failed: {str(e)[:200]}", status="failed")
        return result


async def _deliver_refine_notification(job: dict, result: dict):
    """Send refinement completion notification.

    Discord gets the FULL revised document content (auto-chunked).
    Pushover gets a short alert.
    """
    notify_user = job.get("notify_user", job.get("created_by", ""))
    doc_id = job.get("config", {}).get("doc_id", "?")
    instructions = job.get("config", {}).get("instructions", "?")
    job_id = job["id"]

    if result.get("success"):
        new_doc_id = result.get("doc_id", "?")
        word_count = result.get("word_count", 0)
        version = result.get("version", 2)
        sources_read = result.get("sources_read", 0)
        full_content = result.get("full_content", "")

        header = (
            f"📋 Research refinement complete: {doc_id} → {new_doc_id} (v{version})"
            f"\nInstructions: {instructions[:100]}"
            f"\n{word_count} words, {sources_read} additional sources"
            f"\nOriginal document {doc_id} is preserved."
            f"\n---\n"
        )
        discord_msg = header + full_content if full_content else header + "(use get_doc to read)"

        pushover_msg = (
            f"Research refinement complete: {doc_id} → {new_doc_id} (v{version})"
            f"\n{word_count} words, {sources_read} new sources"
        )
    elif result.get("error") == "Cancelled":
        discord_msg = f"🚫 Research refinement cancelled for {doc_id}"
        pushover_msg = discord_msg
    else:
        discord_msg = f"❌ Refinement failed for {doc_id}: {result.get('error', 'unknown')[:200]}"
        pushover_msg = discord_msg

    # Discord DM — full content, auto-chunked
    try:
        from discord_bot import send_dm
        await send_dm(notify_user, discord_msg)
        logger.info("REFINE [%s]: Discord notification sent to %s (%d chars)",
                     job_id, notify_user, len(discord_msg))
    except Exception as e:
        logger.error("REFINE [%s]: Discord notification failed: %s", job_id, e)

    # Pushover (configured users only)
    try:
        from tools.pushover_tool import is_pushover_user, send_pushover_notification
        if is_pushover_user(notify_user):
            from discord_bot import strip_entity_ids
            send_pushover_notification(
                notify_user,
                strip_entity_ids(pushover_msg),
                cooldown_seconds=0,
            )
    except Exception as e:
        logger.error("REFINE [%s]: Pushover notification failed: %s", job_id, e)

    # WebSocket — push to web UI if user is connected
    try:
        from connections import manager
        await manager.send_to_user(notify_user, {
            "type": "notification",
            "source": "refine",
            "message": discord_msg,
            "user_id": notify_user,
        })
    except Exception as e:
        logger.error("REFINE [%s]: WebSocket notification failed: %s", job_id, e)

    # Log to chat history
    try:
        from chatlog_store import save_notification
        save_notification(notify_user, discord_msg, context="refine_notification")
    except Exception as e:
        logger.error("REFINE [%s]: Failed to log to chat history: %s", job_id, e)


# ---------------------------------------------------------------------------
# Scheduler integration
# ---------------------------------------------------------------------------

# Track currently running research jobs to avoid double-starting
_running_jobs: set[str] = set()


async def check_and_run_research():
    """Called from the scheduler loop. Picks up due research jobs and runs them."""
    from job_store import get_pending_research_jobs, record_run

    pending = get_pending_research_jobs()
    if not pending:
        return

    for job in pending:
        job_id = job["id"]
        if job_id in _running_jobs:
            continue  # already running

        _running_jobs.add(job_id)
        logger.info("RESEARCH [%s]: Starting background research: %s",
                     job_id, job.get("config", {}).get("query", "?")[:60])

        # Fire and forget — run in thread pool
        asyncio.get_event_loop().create_task(_run_and_notify(job))


async def _run_and_notify(job: dict):
    """Run research in a thread and deliver notification when done."""
    from job_store import record_run
    job_id = job["id"]

    try:
        result = await asyncio.to_thread(_run_research_pipeline, job)

        # Record the run
        success = result.get("success", False)
        summary = result.get("error") or f"Doc: {result.get('doc_id', '?')}"
        record_run(job_id, summary[:500], success=success)

        # Deliver notification (unless cancelled — still notify but different message)
        await _deliver_research_notification(job, result)

    except Exception as e:
        logger.error("RESEARCH [%s]: Unhandled error: %s", job_id, e, exc_info=True)
        try:
            from job_store import update_job_progress
            update_job_progress(job_id, f"Failed: {str(e)[:200]}", status="failed")
        except Exception:
            pass
    finally:
        _running_jobs.discard(job_id)


async def check_and_run_refine_jobs():
    """Called from the scheduler loop. Picks up pending refine jobs and runs them."""
    from job_store import get_pending_refine_jobs, record_run

    pending = get_pending_refine_jobs()
    if not pending:
        return

    for job in pending:
        job_id = job["id"]
        if job_id in _running_jobs:
            continue

        _running_jobs.add(job_id)
        logger.info("REFINE [%s]: Starting refinement for %s",
                     job_id, job.get("config", {}).get("doc_id", "?"))

        asyncio.get_event_loop().create_task(_run_and_notify_refine(job))


async def _run_and_notify_refine(job: dict):
    """Run refinement in a thread and deliver notification when done."""
    from job_store import record_run
    job_id = job["id"]

    try:
        result = await asyncio.to_thread(_run_refine_pipeline, job)

        success = result.get("success", False)
        summary = result.get("error") or f"Revised doc: {result.get('doc_id', '?')}"
        record_run(job_id, summary[:500], success=success)

        await _deliver_refine_notification(job, result)

    except Exception as e:
        logger.error("REFINE [%s]: Unhandled error: %s", job_id, e, exc_info=True)
        try:
            from job_store import update_job_progress
            update_job_progress(job_id, f"Failed: {str(e)[:200]}", status="failed")
        except Exception:
            pass
    finally:
        _running_jobs.discard(job_id)
