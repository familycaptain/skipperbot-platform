"""Home App Handlers."""
from image_link_registry import register_image_link_handler
from apps.home import data as _dl

register_image_link_handler("home_issue", _dl.link_issue_image)
register_image_link_handler("home_appliance", _dl.link_appliance_image)
register_image_link_handler("home_insurance_policy", _dl.link_policy_image)
