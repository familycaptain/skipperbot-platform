"""Channel tagging for chat turns (issue #23).

A chat turn records the *surface* it originated on (web / voice / discord / …) in a
``channel`` column. The web-UI history reload shows only web-originated turns, while
persistence, session continuity, and memory/recall stay cross-surface.

These helpers are deliberately **DB-free** (no psycopg2 / data_layer imports) so the
bound test runs on box-2's stdlib unittest venv. The SQL the read path uses is kept
here too (``WEB_VISIBLE_SQL``) so the predicate and the query cannot drift.
"""

WEB = "web"
VOICE = "voice"

# SQL fragment the web-history read applies. Kept beside is_web_visible() so the
# in-DB filter and the in-memory predicate stay in lockstep. NULL (legacy/untagged)
# is treated as web so existing history is never hidden before the backfill runs.
WEB_VISIBLE_SQL = "(channel = 'web' OR channel IS NULL)"


def normalize_channel(raw) -> str:
    """WRITE-side normalization. None / '' / whitespace become 'web'; an explicit
    surface value is lowercased and trimmed (so 'Voice' / ' voice ' -> 'voice')."""
    if raw is None:
        return WEB
    s = str(raw).strip().lower()
    return s or WEB


def is_web_visible(channel) -> bool:
    """READ predicate: is this turn shown in the web history reload? True for 'web'
    and for legacy-untagged turns (None); every explicit non-web surface
    ('voice', 'discord', 'mobile', …) is hidden. Assumes values were normalized at
    rest by the WRITE seam, so it matches 'web' exactly and does not re-normalize."""
    return channel is None or channel == WEB


def select_display_turns(turns, channel: str = WEB):
    """Filter turn dicts to those visible on the given display channel. Only 'web'
    scoping is defined today; any other channel returns the turns unfiltered (the
    endpoint's default-all-turns contract for companion clients)."""
    if channel != WEB:
        return list(turns)
    return [t for t in turns if is_web_visible(t.get("channel"))]
