"""Timeline app.

Family journal / microblog. Owns three tables in ``app_timeline``:

- ``timeline_posts`` — one row per post, body stored as a linked
  document via ``app_platform.documents``.
- ``timeline_photos`` — carousel attachments keyed by ``post_id``.
- ``timeline_tag_index`` — denormalised tag → count for the sidebar.

The platform's auto-activity log (``app_platform/activity.py``) writes
*personal* timeline posts directly into ``app_timeline.timeline_posts``
whenever any app fires ``digest_record`` with a non-empty ``by``. That
write path stays raw SQL — not a circular import on this package —
but it inserts the same shape this app understands (with
``visibility='personal'``).
"""
