"""Meals App Job Handlers."""
from config import logger
from image_link_registry import register_image_link_handler
from apps.meals import data as _dl_meals
from app_platform.events import subscribe

register_image_link_handler("meal", _dl_meals.link_meal_photo)


@subscribe("config.changed")
def _on_config_changed(event: dict) -> None:
    """Re-reconcile the dinner schedule when the operator changes its time.

    Fires on every ``config.changed`` (value-free {scope,key}); we act only for
    our own setting. Fault-isolated by the event bus, and reconcile is
    fail-closed, so this can never break a config write.
    """
    if event.get("scope") == "app:meals" and event.get("key") == "dinner_inquiry_time":
        from apps.meals.schedule import reconcile_dinner_schedule
        reconcile_dinner_schedule()


def handle_dinner_check(job: dict, ctx) -> str:
    """Check if tonight's dinner was logged. If not, send a notification to the user."""
    from datetime import date
    from apps.meals import data as _dl
    from app_platform.notifications import create_notification
    from data_layer.users import get_primary_user

    ctx.update_progress(20, "Checking dinner log for today...")

    today = date.today().isoformat()
    existing = _dl.get_meal_log_for_date(today, "dinner")

    if existing:
        logger.info("MEALS_DINNER_CHECK: Already logged for %s: %s",
                    today, existing.get("description"))
        ctx.update_progress(100, "Dinner already logged")
        return f"Dinner already logged for {today}: {existing.get('description', '')}"

    ctx.update_progress(60, "No dinner logged — sending notification...")

    # Route to the canonical household user (the person who owns this Skipper),
    # not a literal 'user'. Fall back to 'user' only if no primary is resolvable.
    recipient = get_primary_user() or "user"

    create_notification(
        recipient=recipient,
        message="🍽️ What did we have for dinner tonight? Reply and I'll log it and update the meal library!",
        source_type="meals_dinner_check",
        source_id=today,
        channel="both",
        delivered=False,
    )

    logger.info("MEALS_DINNER_CHECK: No dinner logged for %s — notification sent to %s",
                today, recipient)
    ctx.update_progress(100, "Notification sent")
    return f"No dinner logged for {today} — notification sent to {recipient}"
