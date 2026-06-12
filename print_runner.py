"""Print Runner
==============
Background pipeline that prints a d-* document to the default physical printer.

Pipeline:
  1. Load document content (markdown)
  2. Convert markdown → styled HTML
  3. Convert HTML → PDF (fallback chain: weasyprint → Chrome headless → wkhtmltopdf)
  4. Send PDF to default printer via `lpr`
  5. Notify user on completion

Runs in a thread via asyncio.to_thread so it doesn't block the event loop.
"""

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime

from config import logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Markdown → styled HTML
# ---------------------------------------------------------------------------

_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 12pt;
    line-height: 1.6;
    color: #222;
    max-width: 7.5in;
    margin: 0.5in auto;
    padding: 0;
}
h1 { font-size: 20pt; margin-top: 0.5em; border-bottom: 2px solid #333; padding-bottom: 0.2em; }
h2 { font-size: 16pt; margin-top: 1em; border-bottom: 1px solid #aaa; padding-bottom: 0.15em; }
h3 { font-size: 13pt; margin-top: 0.8em; }
h4 { font-size: 12pt; font-style: italic; }
blockquote {
    border-left: 3px solid #888;
    margin-left: 0;
    padding: 0.3em 1em;
    color: #555;
    background: #f9f9f9;
}
code {
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 10pt;
    background: #f4f4f4;
    padding: 0.1em 0.3em;
    border-radius: 3px;
}
pre {
    background: #f4f4f4;
    padding: 0.8em;
    border-radius: 4px;
    overflow-x: auto;
    font-size: 10pt;
}
pre code { background: none; padding: 0; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 0.8em 0;
    font-size: 11pt;
}
th, td {
    border: 1px solid #ccc;
    padding: 0.4em 0.6em;
    text-align: left;
}
th { background: #f0f0f0; font-weight: 600; }
ul, ol { padding-left: 1.5em; }
li { margin-bottom: 0.2em; }
a { color: #0366d6; text-decoration: none; }
hr { border: none; border-top: 1px solid #ddd; margin: 1.5em 0; }
img { max-width: 100%; }
@media print {
    body { margin: 0; max-width: none; }
    a[href]:after { content: " (" attr(href) ")"; font-size: 9pt; color: #666; }
}
"""


def _markdown_to_html(md_content: str, title: str = "Document") -> str:
    """Convert markdown to a fully styled HTML document.

    Tries the `markdown` library first, falls back to basic regex conversion.
    """
    html_body = ""

    # Try Python markdown library
    try:
        import markdown
        html_body = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "toc", "nl2br"],
        )
    except ImportError:
        # Fallback: basic regex-based conversion
        html_body = _basic_md_to_html(md_content)

    return (
        "<!DOCTYPE html>\n"
        "<html><head>\n"
        f"<meta charset='utf-8'>\n"
        f"<title>{_escape_html(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head><body>\n"
        f"{html_body}\n"
        "</body></html>"
    )


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _basic_md_to_html(md: str) -> str:
    """Minimal markdown→HTML for when the `markdown` library isn't available."""
    lines = md.split("\n")
    html_lines = []
    in_code_block = False
    in_list = False

    for line in lines:
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                html_lines.append("<pre><code>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(_escape_html(line))
            continue

        # Close list if not a list item
        if in_list and not re.match(r"^\s*[-*+]\s", line) and line.strip():
            html_lines.append("</ul>")
            in_list = False

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            html_lines.append(f"<h{level}>{_inline_md(m.group(2))}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", line):
            html_lines.append("<hr>")
            continue

        # Blockquote
        if line.startswith(">"):
            content = line.lstrip("> ")
            html_lines.append(f"<blockquote>{_inline_md(content)}</blockquote>")
            continue

        # Unordered list
        m = re.match(r"^\s*[-*+]\s+(.*)", line)
        if m:
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline_md(m.group(1))}</li>")
            continue

        # Empty line
        if not line.strip():
            html_lines.append("")
            continue

        # Paragraph
        html_lines.append(f"<p>{_inline_md(line)}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_code_block:
        html_lines.append("</code></pre>")

    return "\n".join(html_lines)


def _inline_md(text: str) -> str:
    """Handle inline markdown: bold, italic, code, links."""
    text = _escape_html(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


# ---------------------------------------------------------------------------
# HTML → PDF (fallback chain)
# ---------------------------------------------------------------------------

def _html_to_pdf(html_path: str, pdf_path: str) -> tuple[bool, str]:
    """Convert HTML file to PDF. Tries multiple methods.

    Returns (success, method_used_or_error).
    """
    # Method 1: weasyprint (Python library)
    try:
        import weasyprint
        weasyprint.HTML(filename=html_path).write_pdf(pdf_path)
        return True, "weasyprint"
    except ImportError:
        pass
    except Exception as e:
        logger.warning("PRINT: weasyprint failed: %s", e)

    # Method 2: Chrome / Chromium / Edge headless (cross-platform). On Windows,
    # Microsoft Edge is always installed and is Chromium-based, so this path needs
    # no extra software there.
    from pathlib import Path
    _pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    _pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    chrome_candidates = [
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        # Windows
        rf"{_pf}\Google\Chrome\Application\chrome.exe",
        rf"{_pf86}\Google\Chrome\Application\chrome.exe",
        rf"{_pf86}\Microsoft\Edge\Application\msedge.exe",
        rf"{_pf}\Microsoft\Edge\Application\msedge.exe",
        # Linux / anything on PATH
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("microsoft-edge"),
        shutil.which("msedge"),
    ]
    # Path.as_uri() yields a correct file:// URL on every OS (handles Windows
    # drive letters and spaces — plain "file://{path}" breaks on Windows).
    file_url = Path(html_path).as_uri()
    for chrome_path in chrome_candidates:
        if chrome_path and os.path.exists(chrome_path):
            try:
                subprocess.run(
                    [chrome_path, "--headless", "--disable-gpu", "--no-sandbox",
                     f"--print-to-pdf={pdf_path}", file_url],
                    capture_output=True, text=True, timeout=30,
                )
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                    return True, f"chrome-headless ({os.path.basename(chrome_path)})"
            except Exception as e:
                logger.warning("PRINT: Chrome headless failed (%s): %s", chrome_path, e)

    # Method 3: wkhtmltopdf
    wk = shutil.which("wkhtmltopdf")
    if wk:
        try:
            result = subprocess.run(
                [wk, "--quiet", "--enable-local-file-access", html_path, pdf_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                return True, "wkhtmltopdf"
        except Exception as e:
            logger.warning("PRINT: wkhtmltopdf failed: %s", e)

    # Method 4: pandoc
    pandoc = shutil.which("pandoc")
    if pandoc:
        try:
            result = subprocess.run(
                [pandoc, html_path, "-o", pdf_path, "--from=html"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                return True, "pandoc"
        except Exception as e:
            logger.warning("PRINT: pandoc failed: %s", e)

    return False, (
        "No PDF converter available. Install one of: "
        "pip install weasyprint, or Google Chrome (headless), "
        "or brew install wkhtmltopdf, or brew install pandoc"
    )


# ---------------------------------------------------------------------------
# Print via lpr
# ---------------------------------------------------------------------------

def _default_printer() -> str:
    """The configured printer from Settings → Integrations → "Default printer".

    Either an ``ipp://``/``ipps://`` network-printer URL (used on any OS, headless)
    or a CUPS queue name. Blank = the host's default CUPS queue.
    """
    try:
        from app_platform import settings as _settings
        return (_settings.get("default_printer", scope="platform", default="") or "").strip()
    except Exception:
        return ""


def _get_available_printers() -> list[str]:
    """Discover available CUPS queues (IPP printers are addressed by URL)."""
    import print_backends
    return print_backends.list_printers()


def _print_pdf(pdf_path: str, copies: int = 1) -> tuple[bool, str]:
    """Send a PDF to the configured printer via the pluggable backend.

    IPP (network, OS-independent, headless) when a ``ipp://`` URL is configured;
    CUPS/``lpr`` otherwise. See print_backends.py.
    """
    import print_backends
    return print_backends.print_pdf(pdf_path, copies=copies, printer=_default_printer())


# ---------------------------------------------------------------------------
# Recipe → Markdown
# ---------------------------------------------------------------------------

def _load_recipe_as_markdown(recipe_id: str) -> tuple[str, str]:
    """Load a recipe and return (markdown_content, title).

    Raises ValueError if recipe not found.
    """
    from apps.recipes.data import get_recipe

    recipe = get_recipe(recipe_id)
    if not recipe:
        raise ValueError(f"Recipe {recipe_id} not found")

    title = recipe.get("title") or "Recipe"
    lines = [f"# {title}\n"]

    # Description
    if recipe.get("description"):
        lines.append(f"*{recipe['description']}*\n")

    # Meta line
    meta = []
    if recipe.get("prep_time_min") is not None:
        meta.append(f"**Prep:** {recipe['prep_time_min']} min")
    if recipe.get("cook_time_min") is not None:
        meta.append(f"**Cook:** {recipe['cook_time_min']} min")
    total = (recipe.get("prep_time_min") or 0) + (recipe.get("cook_time_min") or 0)
    if total:
        meta.append(f"**Total:** {total} min")
    if recipe.get("servings"):
        meta.append(f"**Servings:** {recipe['servings']}")
    if meta:
        lines.append(" | ".join(meta) + "\n")

    # Categories
    if recipe.get("categories"):
        lines.append("**Categories:** " + ", ".join(recipe["categories"]) + "\n")

    # Ingredients
    ingredients = recipe.get("ingredients") or []
    if ingredients:
        lines.append("## Ingredients\n")
        for ing in ingredients:
            qty = ing.get("quantity", "")
            unit = ing.get("unit", "")
            item = ing.get("item", "")
            parts = [str(qty)] if qty else []
            if unit:
                parts.append(unit)
            parts.append(item)
            lines.append(f"- {' '.join(parts)}")
        lines.append("")

    # Steps
    steps = recipe.get("steps") or []
    if steps:
        lines.append("## Instructions\n")
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    # Chef Comments
    if recipe.get("chef_comments"):
        lines.append("## Chef Comments\n")
        lines.append(recipe["chef_comments"] + "\n")

    # Notes
    if recipe.get("notes"):
        lines.append("## Notes\n")
        lines.append(recipe["notes"] + "\n")

    # Source
    if recipe.get("source_url"):
        lines.append(f"---\n*Source: {recipe['source_url']}*\n")

    return "\n".join(lines), title


# ---------------------------------------------------------------------------
# Main pipeline (runs in thread via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _run_print_pipeline(job: dict) -> dict:
    """Execute the full print pipeline synchronously.

    Returns dict with: success, method, error.
    """
    from app_platform.jobs import update_job_progress, get_job

    job_id = job["id"]
    config = job.get("config", {})
    doc_id = config.get("doc_id", "")
    recipe_id = config.get("recipe_id", "")
    copies = config.get("copies", 1)

    result = {"success": False, "method": "", "error": ""}

    try:
        # --- Step 1: Load content ---
        if recipe_id:
            update_job_progress(job_id, f"Loading recipe {recipe_id}...", status="running")
            md_content, title = _load_recipe_as_markdown(recipe_id)
        else:
            update_job_progress(job_id, f"Loading document {doc_id}...", status="running")
            from app_platform.documents import get_doc
            doc = get_doc(doc_id)
            if not doc:
                result["error"] = f"Document {doc_id} not found"
                update_job_progress(job_id, result["error"], status="failed")
                return result
            md_content = doc.get("content", "")
            title = doc.get("title", "Document")

        entity_label = recipe_id or doc_id
        if not md_content.strip():
            result["error"] = f"{entity_label} has no content"
            update_job_progress(job_id, result["error"], status="failed")
            return result

        # Check cancellation
        fresh = get_job(job_id)
        if fresh and fresh.get("cancelled"):
            result["error"] = "Cancelled"
            return result

        # --- Step 2: Convert to HTML ---
        update_job_progress(job_id, "Converting markdown to HTML...")

        html_content = _markdown_to_html(md_content, title=title)

        # Write to temp files
        tmp_dir = tempfile.mkdtemp(prefix="skipperbot_print_")
        html_path = os.path.join(tmp_dir, "document.html")
        pdf_path = os.path.join(tmp_dir, "document.pdf")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # --- Step 3: Convert to PDF ---
        update_job_progress(job_id, "Converting to PDF...")

        pdf_ok, pdf_method = _html_to_pdf(html_path, pdf_path)
        if not pdf_ok:
            result["error"] = pdf_method
            update_job_progress(job_id, f"Failed: {pdf_method}", status="failed")
            _cleanup(tmp_dir)
            return result

        result["method"] = pdf_method
        update_job_progress(job_id, f"PDF created via {pdf_method}. Sending to printer...")

        # Check cancellation
        fresh = get_job(job_id)
        if fresh and fresh.get("cancelled"):
            result["error"] = "Cancelled"
            _cleanup(tmp_dir)
            return result

        # --- Step 4: Print ---
        print_ok, print_msg = _print_pdf(pdf_path, copies=copies)
        if not print_ok:
            result["error"] = print_msg
            update_job_progress(job_id, f"Failed: {print_msg}", status="failed")
            _cleanup(tmp_dir)
            return result

        result["success"] = True
        result["print_msg"] = print_msg   # where/how it was actually sent (backend message)
        update_job_progress(
            job_id,
            f"Printed! {print_msg} (PDF via {pdf_method})",
            status="completed",
        )

        logger.info("PRINT [%s]: Success. Doc: %s, method: %s, copies: %d",
                     job_id, doc_id, pdf_method, copies)

        _cleanup(tmp_dir)
        return result

    except Exception as e:
        result["error"] = str(e)
        logger.error("PRINT [%s]: Pipeline failed: %s", job_id, e, exc_info=True)
        update_job_progress(job_id, f"Failed: {str(e)[:200]}", status="failed")
        return result


def _cleanup(tmp_dir: str):
    """Remove temp directory."""
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Notification delivery
# ---------------------------------------------------------------------------

async def _deliver_print_notification(job: dict, result: dict):
    """Send print completion notification."""
    notify_user = job.get("notify_user", job.get("created_by", ""))
    config = job.get("config", {})
    entity_id = config.get("recipe_id") or config.get("doc_id", "?")
    entity_type = "Recipe" if config.get("recipe_id") else "Document"
    job_id = job["id"]

    if result.get("success"):
        # Report the actual destination/backend ("Sent to … via IPP/lpr"), not the
        # PDF engine — so "it said it printed" is debuggable when nothing comes out.
        dest = result.get("print_msg") or "sent to printer"
        msg = f"🖨️ {entity_type} {entity_id}: {dest} (PDF via {result.get('method', '?')})"
    elif result.get("error") == "Cancelled":
        msg = f"🚫 Print job cancelled for {entity_id}"
    else:
        msg = f"❌ Print failed for {entity_id}: {result.get('error', 'unknown')[:200]}"

    # Discord DM
    try:
        from discord_bot import send_dm
        await send_dm(notify_user, msg)
    except Exception as e:
        logger.error("PRINT [%s]: Discord notification failed: %s", job_id, e)

    # Pushover (configured users only)
    try:
        from tools.pushover_tool import is_pushover_user, send_pushover_notification
        if is_pushover_user(notify_user):
            from discord_bot import strip_entity_ids
            send_pushover_notification(
                notify_user,
                strip_entity_ids(msg),
                cooldown_seconds=0,
            )
    except Exception as e:
        logger.error("PRINT [%s]: Pushover notification failed: %s", job_id, e)

    # Log to chat history
    try:
        from chatlog_store import save_notification
        save_notification(notify_user, msg, context="print_notification")
    except Exception as e:
        logger.error("PRINT [%s]: Failed to log to chat history: %s", job_id, e)


# ---------------------------------------------------------------------------
# Scheduler integration
# ---------------------------------------------------------------------------

_running_print_jobs: set[str] = set()


async def check_and_run_print_jobs():
    """Called from the scheduler loop. Picks up pending print jobs."""
    from app_platform.jobs import get_pending_print_jobs, record_run

    pending = get_pending_print_jobs()
    if not pending:
        return

    for job in pending:
        job_id = job["id"]
        if job_id in _running_print_jobs:
            continue

        _running_print_jobs.add(job_id)
        logger.info("PRINT [%s]: Starting print job for %s",
                     job_id, job.get("config", {}).get("doc_id", "?"))

        asyncio.get_event_loop().create_task(_run_and_notify_print(job))


async def _run_and_notify_print(job: dict):
    """Run print pipeline in a thread and deliver notification."""
    from app_platform.jobs import record_run
    job_id = job["id"]

    try:
        result = await asyncio.to_thread(_run_print_pipeline, job)

        success = result.get("success", False)
        summary = result.get("error") or f"Printed via {result.get('method', '?')}"
        record_run(job_id, summary[:500], success=success)

        await _deliver_print_notification(job, result)

    except Exception as e:
        logger.error("PRINT [%s]: Unhandled error: %s", job_id, e, exc_info=True)
        try:
            from app_platform.jobs import update_job_progress
            update_job_progress(job_id, f"Failed: {str(e)[:200]}", status="failed")
        except Exception:
            pass
    finally:
        _running_print_jobs.discard(job_id)
