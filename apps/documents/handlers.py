"""Documents — event + thinking-domain subscriptions.

Registers the **document** thinking domain with the platform's
thinking scheduler so it gets driven on the configured cron schedule
(default: every 30 minutes from manifest.yaml; faster during catch-up
when there are >500 unprocessed memories).
"""

from __future__ import annotations

from domain_modules import register_domain
from apps.documents.domain import document_domain_handler

# The scheduler will invoke document_domain_handler on the cron
# configured in manifest.yaml. The handler signature matches the
# observe → evaluate → act contract:
#
#     async def document_domain_handler(domain: dict, budget_status: dict) -> dict
register_domain("document", document_domain_handler)
