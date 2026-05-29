"""System app.

Owns the system-health dashboard surface: record counts across every
installed app, DB size, latest job + backup, document-curation
cursor, and a process-level snapshot (PID, RSS, uptime).

The data is pieced together from each owning app's tables. Where an
app has been packaged into its own ``app_<id>`` schema, this app
reads the qualified name; where the data still lives in the
platform's ``public.*`` (goals, memories, chat_turns, etc. until
those apps are packaged), it stays unqualified and falls through to
the public search_path.

System owns no migrations of its own — it only reads — but it does
own one REST route (`/api/apps/system/metrics`). The admin
``/api/admin/*`` endpoints stay in agent.py because they affect
platform-wide state (graceful restart, etc.).
"""
