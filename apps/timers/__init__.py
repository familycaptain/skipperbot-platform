"""Timers app package — short in-memory countdown timers.

Timers are ephemeral (in-process asyncio tasks); the fired notification is the
only persisted artifact. See ``store`` (registry), ``scheduler`` (firing +
graceful shutdown), and ``tools`` (the chat/voice tools).
"""
