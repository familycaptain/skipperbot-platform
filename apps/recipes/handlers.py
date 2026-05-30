"""Recipes App Handlers."""
from image_link_registry import register_image_link_handler
from apps.recipes import data as _dl

register_image_link_handler("recipe", _dl.link_image)
