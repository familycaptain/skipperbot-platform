"""Newsletter Job Handlers — Registered via manifest.yaml.

Three handler types:
  - newsletter_breadth:  Nightly breadth data collection (VIX, sector_breadth_pct, sector_momentum)
  - newsletter_generate: Full morning newsletter generation pipeline
  - newsletter_send:     Email delivery via Resend (triggered after generate)
"""

import asyncio
import logging
from datetime import date

logger = logging.getLogger(__name__)


async def handle_breadth(job: dict, ctx) -> str:
    """Collect market breadth indicators and store in DB.

    Schedule: nightly after market close (~5:00 PM CT).
    """
    from apps.newsletter.breadth import collect_breadth

    config = job.get("config") or {}
    target_date_str = config.get("date")
    target_date = date.fromisoformat(target_date_str) if target_date_str else None

    try:
        row = await asyncio.to_thread(collect_breadth, target_date)
    except Exception as e:
        logger.error("NEWSLETTER BREADTH: Failed: %s", e, exc_info=True)
        return f"Breadth collection failed: {e}"

    ctx.update_progress(100, "Breadth collected")
    return (
        f"Breadth collected for {row.get('snapshot_date')} — "
        f"VIX={row.get('vix')}, SectorBreadth={row.get('sector_breadth_pct')}, SectorMomentum={row.get('sector_momentum')}"
    )


async def handle_generate(job: dict, ctx) -> str:
    """Run the full newsletter generation pipeline for a given date.

    Schedule: ~6:00 AM CT (runs before 8:00 AM ET delivery).
    Generates charts, fetches pre-market data, runs LLM synthesis,
    assembles markdown + HTML, stores in DB.
    """
    from apps.newsletter.runner import run_newsletter_pipeline

    config = job.get("config") or {}
    target_date_str = config.get("date")
    target_date = date.fromisoformat(target_date_str) if target_date_str else date.today()

    def progress_fn(pct, msg):
        ctx.update_progress(pct, msg)

    try:
        result = await asyncio.to_thread(
            run_newsletter_pipeline,
            edition_date=target_date,
            progress_fn=progress_fn,
        )
    except Exception as e:
        logger.error("NEWSLETTER GENERATE: Pipeline failed: %s", e, exc_info=True)
        return f"Newsletter generation failed: {e}"

    ctx.update_progress(95, "Market brief generated - sending email")
    edition_id = result.get("edition_id", "unknown")
    notify_user = job.get("notify_user") or job.get("created_by", "")
    test_email = config.get("test_email", "").strip()

    try:
        from apps.newsletter.sender import send_edition
        from apps.newsletter.data import get_config
        recipients_override = [test_email] if test_email else None
        send_result = await asyncio.to_thread(send_edition, edition_id, recipients_override)
        recipients = send_result.get("recipients", [])
        cfg = await asyncio.to_thread(get_config)
        product_name = ((cfg or {}).get("product_name") or "").strip() or "Systematic Market Brief"
        ctx.update_progress(100, f"Sent to {len(recipients)} recipient(s)")

        if notify_user:
            try:
                from app_platform.notifications import create_notification
                create_notification(
                    recipient=notify_user,
                    message=f"{product_name} for {target_date} has been generated and sent to {len(recipients)} recipient(s).",
                    source_type="newsletter",
                    source_id=edition_id,
                    channel="both",
                )
            except Exception as ne:
                logger.warning("NEWSLETTER GENERATE: Notification failed (non-fatal): %s", ne)

        return (
            f"{product_name} generated and sent: edition_id={edition_id}, date={target_date}, "
            f"recipients={recipients}"
        )
    except Exception as e:
        logger.error("NEWSLETTER GENERATE: Send failed after successful generation: %s", e, exc_info=True)
        ctx.update_progress(100, "Generated (send failed - check logs)")
        return (
            f"Market brief generated but send failed: edition_id={edition_id}, date={target_date}, "
            f"error={e}"
        )


async def handle_send(job: dict, ctx) -> str:
    """Send a generated newsletter edition via email (Resend).

    Triggered manually or after handle_generate completes.
    Requires edition to be in 'generated' status.
    """
    from apps.newsletter.sender import send_edition
    from apps.newsletter.data import get_config

    config = job.get("config") or {}
    edition_id = config.get("edition_id")
    if not edition_id:
        return "Missing edition_id in job config"

    try:
        result = await asyncio.to_thread(send_edition, edition_id)
    except Exception as e:
        logger.error("NEWSLETTER SEND: Failed: %s", e, exc_info=True)
        return f"Newsletter send failed: {e}"

    cfg = await asyncio.to_thread(get_config)
    product_name = ((cfg or {}).get("product_name") or "").strip() or "Systematic Market Brief"
    ctx.update_progress(100, "Market brief sent")
    recipients = result.get("recipients", [])
    return f"{product_name} sent to {len(recipients)} recipient(s): {', '.join(recipients)}"
