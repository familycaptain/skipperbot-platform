"""Auto App Handlers."""
from image_link_registry import register_image_link_handler
from apps.auto import data as _dl

register_image_link_handler("auto_issue", _dl.link_image_to_issue)
