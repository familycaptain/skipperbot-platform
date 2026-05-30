"""Newsletter Email Sender — Delivers generated editions via Resend.

Uses the Resend API to send HTML emails with embedded chart images.
Charts are base64-encoded and attached as inline CID attachments so
images travel with the email without requiring external hosting.

Resend API key is read from the RESEND_API_KEY environment variable.

Install: pip install resend
Docs: https://resend.com/docs/send-with-python
"""

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _replace_chart_placeholders(content_md: str) -> str:
    """Replace [CHART: chart_type] placeholders with HTML img CID tags.

    Matches both single-line:
        [CHART: normalized_growth_30d]
    And multi-line block forms (chart spec indented below the tag):
        [CHART: sector_rrg]
          Type: ...
          Tickers: ...
    Only the tag line is replaced; indented spec lines below are stripped.
    """
    import re

    lines = content_md.splitlines()
    out = []
    skip_indent = False

    for line in lines:
        # Start of a chart block
        m = re.match(r"^\[CHART:\s*([^\]]+)\]", line.strip())
        if m:
            chart_type = m.group(1).strip()
            out.append(
                f'<p><img src="cid:{chart_type}" alt="{chart_type}" '
                f'style="max-width:100%;height:auto;display:block;margin:8px 0;" /></p>'
            )
            skip_indent = True
            continue

        # Skip indented spec lines that follow a chart tag
        if skip_indent:
            if line.startswith("  ") or line.startswith("\t") or line.strip() == "":
                continue
            else:
                skip_indent = False

        out.append(line)

    return "\n".join(out)


def _markdown_to_html(content_md: str) -> str:
    """Convert newsletter markdown to HTML.

    Replaces [CHART: xxx] placeholders with inline CID img tags first,
    then converts the rest with the markdown library.
    Falls back to pre-wrapped plain text if markdown is not installed.
    """
    content_md = _replace_chart_placeholders(content_md)

    try:
        import markdown
        html_body = markdown.markdown(
            content_md,
            extensions=["tables", "fenced_code", "nl2br"],
        )
    except ImportError:
        logger.warning("SENDER: `markdown` library not installed, falling back to plain text")
        escaped = content_md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html_body = f"<pre>{escaped}</pre>"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Georgia, 'Times New Roman', serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #1a1a1a; line-height: 1.6; }}
  h1 {{ font-size: 2em; border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h2 {{ font-size: 1.4em; margin-top: 2em; color: #222; border-bottom: 1px solid #ccc; padding-bottom: 4px; }}
  h3 {{ font-size: 1.1em; color: #444; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f5f5f5; font-weight: bold; }}
  tr:nth-child(even) {{ background: #fafafa; }}
  code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: monospace; }}
  pre {{ background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; }}
  blockquote {{ border-left: 3px solid #ccc; padding-left: 12px; color: #555; margin-left: 0; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 2em 0; }}
  img {{ max-width: 100%; height: auto; display: block; margin: 1em 0; }}
  em {{ color: #555; }}
  strong {{ color: #111; }}
  .footer {{ font-size: 0.85em; color: #888; margin-top: 3em; padding-top: 1em; border-top: 1px solid #eee; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""


def _build_inline_attachments(chart_paths: list[dict]) -> list[dict]:
    """Build Resend inline attachment objects from chart file paths.

    Each item in chart_paths should have: file_path, chart_type.
    Returns list of Resend attachment dicts with content_id for CID embedding.
    """
    attachments = []
    for chart in chart_paths:
        fp = chart.get("file_path")
        if not fp or not Path(fp).exists():
            logger.warning("SENDER: Chart file not found: %s", fp)
            continue
        try:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            cid = chart.get("chart_type", Path(fp).stem)
            attachments.append({
                "filename": Path(fp).name,
                "content": b64,
                "content_type": "image/png",
                "content_disposition": "inline",
                "content_id": cid,
            })
        except Exception as e:
            logger.warning("SENDER: Failed to read chart %s: %s", fp, e)

    return attachments


def send_edition(edition_id: str, recipients: list[str] | None = None) -> dict:
    """Send a generated newsletter edition via Resend.

    Args:
        edition_id:  ID of an edition with status='generated'.
        recipients:  Optional override list of email addresses. If None, active
                     subscribers are loaded from the database. Falls back to
                     email_recipients config field if no subscribers exist.

    Returns:
        dict with recipients, resend_message_id, status.
    """
    from apps.newsletter.data import (
        get_edition, get_charts, get_config, update_edition_status,
        get_active_subscriber_emails,
    )

    edition = get_edition(edition_id)
    if not edition:
        raise ValueError(f"Edition not found: {edition_id}")
    if edition.get("status") not in ("generated", "error"):
        raise ValueError(f"Edition {edition_id} is not in 'generated' status (got: {edition.get('status')})")

    cfg = get_config() or {}
    product_name = (cfg.get("product_name") or "").strip() or "Systematic Market Brief"
    sender_name = (cfg.get("from_name") or "").strip() or product_name

    if recipients is None:
        recipients = get_active_subscriber_emails()
        if not recipients:
            legacy = cfg.get("email_recipients") or []
            if isinstance(legacy, str):
                import json
                legacy = json.loads(legacy)
            recipients = legacy

    if not recipients:
        raise ValueError("No active subscribers and no email_recipients configured")

    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise ValueError("RESEND_API_KEY environment variable not set")

    content_md = edition.get("content_md") or ""
    content_html = edition.get("content_html") or _markdown_to_html(content_md)

    charts = get_charts(edition_id)
    attachments = _build_inline_attachments(charts)

    edition_date = edition.get("edition_date", str(edition_id))
    subject = f"{product_name} | {edition_date}"

    try:
        import resend
        resend.api_key = api_key

        params = {
            "from": f"{sender_name} <{cfg.get('from_address', 'newsletter@example.com')}>",
            "to": recipients,
            "subject": subject,
            "html": content_html,
        }
        if attachments:
            params["attachments"] = attachments

        response = resend.Emails.send(params)
        # resend v2 returns an object with .id; v1 returned a dict
        message_id = getattr(response, "id", None) or (response.get("id", "unknown") if hasattr(response, "get") else "unknown")

        logger.info("SENDER: Sent edition %s to %d recipient(s), message_id=%s",
                    edition_id, len(recipients), message_id)

        update_edition_status(edition_id, "sent")

        return {
            "recipients": recipients,
            "resend_message_id": message_id,
            "status": "sent",
        }

    except Exception as e:
        logger.error("SENDER: Failed to send edition %s: %s", edition_id, e, exc_info=True)
        update_edition_status(edition_id, "error", error_msg=str(e))
        raise
