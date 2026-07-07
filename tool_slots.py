"""tool_slots.py — reusable per-cycle tool-slot mechanism for thinking domains.

Extracted from chat_domain's proven inline slot logic so proactive thinking
domains (DOC_THINK first) expose a LEAN baseline of tool categories plus a few
on-demand swap slots the model fills via request_tools(category), instead of a
hardcoded tool-NAME allowlist that bloats every cycle's prompt.

SECURITY — deny-by-default. A proactive cycle is human-out-of-the-loop and its
working inputs can be untrusted, attacker-influenceable content (e.g. document
bodies), so request_tools must NOT be able to reach the whole registry (the
confused-deputy / prompt-injection risk). load_slot enforces a per-domain
ALLOWED-CATEGORY allowlist: a category outside it — or an unknown one — loads NO
slot and fails closed, so a malicious input cannot steer the cycle to self-load a
destructive/sensitive category (user management, backups, credential/settings
admin, bulk-delete). An optional `excluded_tool_names` set is subtracted from the
final surface so a domain never exposes a destructive tool it should not wield,
even when a baseline category happens to include one. Each self-load is logged.

Depends only on tool_router + mcp_client (platform root) — apps import this,
never the reverse (the one-directional dependency rule).

Slots are per-cycle: build a fresh ToolSlots each proactive cycle; nothing is
persisted across cycles.
"""
import logging

import mcp_client
from tool_router import (
    get_category_tool_names,
    get_guides_for_categories,
    list_categories_text,
)

logger = logging.getLogger(__name__)

MAX_TOOLS = 128  # provider hard cap on tools per request


def _norm(category: str) -> str:
    return (category or "").lower().strip()


class ToolSlots:
    """Per-cycle tool-slot state for ONE thinking domain.

    baseline_categories: always-on categories (never evicted) — the lean surface.
    pinned_tools:        custom/META tool SCHEMAS always exposed (never evicted).
    allowed_categories:  deny-by-default allowlist request_tools may load (the
                         baseline is always implicitly allowed). Anything else
                         fails closed.
    capacity:            number of swap slots, sized to the domain's real
                         common-cycle concurrency (NOT a blind inherit of 2).
    excluded_tool_names: tool NAMES subtracted from the final surface even if a
                         baseline/loaded category includes them (destructive
                         tools the domain must never wield).
    """

    def __init__(self, *, baseline_categories, pinned_tools=None,
                 allowed_categories=None, capacity=3, excluded_tool_names=None,
                 domain_label="THINK"):
        self.baseline = [_norm(c) for c in baseline_categories]
        self.pinned_tools = list(pinned_tools or [])
        self.pinned_tool_names = {t["function"]["name"] for t in self.pinned_tools}
        # The allowlist ALWAYS includes the baseline (deny-by-default for the rest).
        self.allowed = {_norm(c) for c in (allowed_categories or [])} | set(self.baseline)
        self.capacity = capacity
        self.excluded_tool_names = set(excluded_tool_names or [])
        self.domain_label = domain_label
        self.slots: list[str] = []  # requested categories, oldest first

    # -- slot mechanics -----------------------------------------------------

    def loaded_categories(self) -> set[str]:
        """Everything currently exposed: baseline (pinned) + the swap slots."""
        return set(self.baseline) | set(self.slots)

    def load_slot(self, category: str) -> tuple:
        """Load a category into a swap slot, deny-by-default.

        Returns (status, loaded, evicted); status ∈ loaded|already|invalid|denied.
        Validates via tool_router.get_category_tool_names (so app:<id> resolves),
        NOT a raw dict-key check. Evicts the OLDEST slot when full; baseline
        categories live outside the slots and are never evicted.
        """
        category = _norm(category)
        if not category or not get_category_tool_names(category):
            logger.info("TOOL SLOTS[%s]: invalid category request [%s]", self.domain_label, category)
            return "invalid", None, None
        if category not in self.allowed:
            # deny-by-default: an out-of-allowlist (e.g. destructive/sensitive) category.
            logger.warning("TOOL SLOTS[%s]: DENIED out-of-allowlist category [%s] (fail-closed)",
                           self.domain_label, category)
            return "denied", None, None
        if category in self.loaded_categories():
            return "already", category, None
        evicted = self.slots.pop(0) if len(self.slots) >= self.capacity else None
        self.slots.append(category)
        logger.info("TOOL SLOTS[%s]: loaded [%s]%s (slots=%s)", self.domain_label, category,
                    f" evicted [{evicted}]" if evicted else "", self.slots)
        return "loaded", category, evicted

    def request_tools_response(self, category: str) -> str:
        """Definitive text response for a request_tools(category) call.

        A valid+allowed category loads (and reports any eviction); an
        out-of-allowlist or unknown category loads NOTHING and returns a
        definitive message + the dynamic catalog, so the loop never spins on a
        bad request.
        """
        status, loaded, evicted = self.load_slot(category)
        if status == "loaded":
            return (f"Loaded the '{loaded}' toolset"
                    + (f" (unloaded '{evicted}' to make room)" if evicted else "")
                    + ". Its tools and guide are now available this cycle.")
        if status == "already":
            return f"The '{loaded}' toolset is already available."
        if status == "denied":
            return (f"The '{category}' toolset isn't available to this domain.\n\n"
                    + self.catalog_text())
        return (f"No such toolset '{category}'.\n\n" + self.catalog_text())

    # -- text builders (all dynamic — no hardcoded category list) -----------

    def catalog_text(self) -> str:
        """The categories THIS domain may request — derived dynamically from the
        registry (list_categories_text) filtered to the allowlist; never a
        hardcoded list."""
        lines, listed = [], set()
        for line in list_categories_text().splitlines():
            name = line.strip().split(":", 1)[0].strip()
            if name in self.allowed:
                lines.append(line)
                listed.add(name)
        # allowed app:<id> categories that list_categories_text doesn't enumerate
        for cat in sorted(self.allowed):
            if cat not in listed:
                lines.append(f"  {cat}")
        return "Toolsets you can request_tools() (deny-by-default — only these):\n" + "\n".join(lines)

    def slot_instructions(self) -> str:
        """The slot-instruction block injected into the domain prompt."""
        loaded = sorted(self.loaded_categories())
        return (
            "## Tool categories (slots)\n"
            f"Loaded now: {', '.join(loaded) if loaded else 'core only'} "
            f"(you have {self.capacity} swap slots, {len(self.slots)} used).\n"
            "To act in an area whose tools you don't see, call request_tools(category) — it loads that "
            "category's tools AND its guide into a slot (auto-unloads your oldest slot if full). You can "
            "only load toolsets available to this domain; never invent a tool you haven't loaded.\n\n"
            + self.catalog_text()
        )

    def guides(self, categories: set[str] | None = None) -> str:
        """Guides for the given categories (default: all currently loaded)."""
        return get_guides_for_categories(categories if categories is not None
                                         else self.loaded_categories())

    # -- tool set assembly --------------------------------------------------

    def _names_for(self, categories) -> set[str]:
        names: set[str] = set()
        for c in categories:
            names |= get_category_tool_names(c)
        return names

    def build_round_tools(self) -> list | None:
        """The tool schemas for the current round: pinned + baseline ∪ loaded-slot
        MCP tools, minus excluded names, capped at MAX_TOOLS.

        Truncation is priority-ordered: pinned + baseline are kept first, then
        slot tools NEWEST-first — so if the cap is hit the OLDEST slot is dropped
        first and a just-requested tool survives into the round it was requested
        for. A slot load can never evict a pinned or baseline tool.
        """
        baseline_names = (self._names_for(self.baseline)
                          - self.excluded_tool_names - self.pinned_tool_names)
        mcp_all = mcp_client.get_openai_tools() if mcp_client.mcp_tools else []
        by_name = {t["function"]["name"]: t for t in mcp_all}

        baseline_tools = [by_name[n] for n in baseline_names if n in by_name]

        # slot tools, NEWEST slot first, excluding anything already in baseline/pinned
        seen = set(baseline_names) | self.pinned_tool_names
        slot_tools = []
        for cat in reversed(self.slots):  # newest first
            for n in sorted(get_category_tool_names(cat) - self.excluded_tool_names):
                if n not in seen and n in by_name:
                    slot_tools.append(by_name[n])
                    seen.add(n)

        combined = list(self.pinned_tools) + baseline_tools + slot_tools
        if len(combined) > MAX_TOOLS:
            logger.warning("TOOL SLOTS[%s]: %d tools exceed cap %d — truncating "
                           "(pinned+baseline kept; oldest slot dropped first)",
                           self.domain_label, len(combined), MAX_TOOLS)
            combined = combined[:MAX_TOOLS]
        return combined or None

    def assert_baseline_nonempty(self) -> list[str]:
        """LIVE assertion (spec-mandated): EACH baseline category must resolve
        INDIVIDUALLY to a non-empty tool set — an aggregate union would hide a
        single mis-keyed/empty category that silently degrades the lean baseline
        to core-only. Returns the list of empty baseline categories (logs ERROR
        for each); empty list means healthy."""
        empty = [c for c in self.baseline if not get_category_tool_names(c)]
        for c in empty:
            logger.error("TOOL SLOTS[%s]: baseline category [%s] resolved to ZERO tools — "
                         "lean baseline degraded; check the category key / app load order",
                         self.domain_label, c)
        return empty
