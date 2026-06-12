"""Platform Images Service
=========================
Stable contract for the platform-level ``image`` entity type — saved images and
generated charts. The data lives in the baseline ``public.images`` table; this
shim forwards to ``data_layer.images`` so apps use one short, stable import path
(documented in ``APP_PACKAGES.md``).

``image`` is a platform entity type, NOT an app. The bundled **Images** app is
just a *viewer* over this store (it registers the ``image`` entity type and
renders a gallery); the table and data layer are platform-level. Mirrors the
``app_platform.documents`` shim pattern.

Usage from an app or platform module:

    from app_platform.images import save_image, get_image

    save_image({"id": "i-ab12cd34", "title": "Sales chart", ...})
    img = get_image("i-ab12cd34")
"""

from __future__ import annotations

from data_layer.images import (
    save_image,
    get_image,
    get_all_images,
    update_image_title,
    delete_image,
)

__all__ = [
    "save_image",
    "get_image",
    "get_all_images",
    "update_image_title",
    "delete_image",
]
