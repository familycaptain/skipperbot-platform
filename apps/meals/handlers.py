"""Meals App Job Handlers."""
from config import logger
from image_link_registry import register_image_link_handler
from apps.meals import data as _dl_meals

register_image_link_handler("meal", _dl_meals.link_meal_photo)


def handle_dinner_check(job: dict, ctx) -> str:
    """Check if tonight's dinner was logged. If not, send a notification to the user."""
    from datetime import date
    from apps.meals import data as _dl
    from app_platform.notifications import create_notification

    ctx.update_progress(20, "Checking dinner log for today...")

    today = date.today().isoformat()
    existing = _dl.get_meal_log_for_date(today, "dinner")

    if existing:
        logger.info("MEALS_DINNER_CHECK: Already logged for %s: %s",
                    today, existing.get("description"))
        ctx.update_progress(100, "Dinner already logged")
        return f"Dinner already logged for {today}: {existing.get('description', '')}"

    ctx.update_progress(60, "No dinner logged — sending notification...")

    create_notification(
        recipient="user",
        message="🍽️ What did we have for dinner tonight? Reply and I'll log it and update the meal library!",
        source_type="meals_dinner_check",
        source_id=today,
        channel="both",
        delivered=False,
    )

    logger.info("MEALS_DINNER_CHECK: No dinner logged for %s — notification sent", today)
    ctx.update_progress(100, "Notification sent")
    return f"No dinner logged for {today} — notification sent to user"
