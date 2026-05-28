"""Test script: push a notification exactly like the meals dinner check job does."""
import os
import dotenv
dotenv.load_dotenv()

from app_platform.notifications import create_notification

notif = create_notification(
    recipient="alice",
    message="🧪 Test notification — did this show up on the web UI?",
    source_type="meals_dinner_check",
    source_id="test",
    channel="both",
    delivered=False,
)

print(f"Created notification: {notif}")
print("Waiting for delivery cycle (~30s)...")
