"""Installable model connectors — MODEL_FLEXIBILITY P2+P3 (issue #44).

Connectors are loaded like optional apps: built-ins ship in-repo (providers/connectors/),
and more install into a gitignored ``models/`` folder (each a ``skipperbot-model-XXX`` clone).
``load_all_connectors()`` scans both at boot and registers each via ``providers.registry`` —
CORE NEVER IMPORTS A CONNECTOR (one-directional dep). Each connector bakes its own model list
+ auth shape; nothing here makes a live call at import.
"""
