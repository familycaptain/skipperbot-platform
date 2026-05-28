"""Notifications — required core app.

Owns the ``app_notifications.notifications`` table and the outbound
delivery loop. Every other app that needs to tell a user something
calls ``app_platform.notifications.create_notification(...)``, which
forwards to this app's store layer; the delivery loop (run from the
reminder scheduler) picks up undelivered rows and dispatches them via
the registered channels (Discord DM, Pushover, WebSocket, chat log,
FCM mobile push).
"""
