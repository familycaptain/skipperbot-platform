#!/usr/bin/env python3
"""Guard: every platform migration must apply cleanly to a FRESH database.

WHY THIS EXISTS
A migration that alters an object the CURRENT baseline no longer creates works fine
on every existing deployment (which migrated forward while the object still existed)
and hard-fails on a brand-new install. `init_db.py` aborts on that error and the
entrypoint refuses to start the agent, so a first-time user gets a PERMANENT boot
loop -- while every already-running instance looks perfectly healthy. The automated
path that would catch it (provisioning an empty DB) is itself blocked by it.

That happened for real: `001_consciousness_log.sql` ran
`ALTER TABLE public.thinking_domains ALTER COLUMN observe_tool DROP NOT NULL`
on columns the regenerated baseline no longer creates. Its comment even claimed
"DROP NOT NULL is a no-op if already nullable" -- true for nullability, false for a
column that does not exist at all.

WHAT IT CHECKS
Statements that REQUIRE a pre-existing column, appearing UNGUARDED at the top level
of a migration, where the column is not created by the baseline nor added by any
earlier migration:
    ALTER TABLE [ONLY] <t> ALTER COLUMN <c> ...
    ALTER TABLE <t> RENAME COLUMN <c> ...
    ALTER TABLE <t> DROP COLUMN <c>          (without IF EXISTS)

Guarded forms are accepted: anything inside a `DO $$ ... $$;` block (which can test
information_schema first), `DROP COLUMN IF EXISTS`, `ADD COLUMN IF NOT EXISTS`.

Deliberately conservative: it flags only columns it can PROVE are absent on a fresh
install, so it does not cry wolf on a correct migration.

Run: python3 scripts/check_migrations_fresh_install.py
Exit 0 = safe. Exit 1 = a migration would break a first-time install.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS = os.path.join(ROOT, "migrations")
BASELINE = "000_baseline.sql"

# Lines inside a CREATE TABLE body that declare a constraint, not a column.
_NOT_A_COLUMN = re.compile(
    r"^\s*(CONSTRAINT|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK|EXCLUDE|LIKE)\b", re.I)


def _strip_do_blocks(sql: str) -> str:
    """Remove `DO $$ ... $$;` bodies — statements in there are the GUARDED form
    (they can consult information_schema before touching anything)."""
    return re.sub(r"DO\s*\$\$.*?\$\$\s*;", " ", sql, flags=re.S | re.I)


def _table_key(raw: str) -> str:
    t = raw.strip().strip('"').lower()
    return t.split(".", 1)[1] if t.startswith("public.") else t


def baseline_columns(sql: str) -> dict:
    """table -> {columns} for every CREATE TABLE in the baseline."""
    out = {}
    for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"]+)\s*\((.*?)\n\s*\)\s*;",
            sql, re.S | re.I):
        cols = set()
        for line in m.group(2).splitlines():
            line = line.strip()
            if not line or line.startswith("--") or _NOT_A_COLUMN.match(line):
                continue
            name = line.split()[0].strip('",').strip('"').lower()
            if name:
                cols.add(name)
        out.setdefault(_table_key(m.group(1)), set()).update(cols)
    return out


def added_columns(sql: str, known: dict) -> None:
    """Fold `ADD COLUMN`s from a migration into the known map (in file order)."""
    for m in re.finditer(
            r"ALTER\s+TABLE\s+(?:ONLY\s+)?([\w.\"]+)\s+ADD\s+COLUMN\s+"
            r"(?:IF\s+NOT\s+EXISTS\s+)?([\w\"]+)", sql, re.I):
        known.setdefault(_table_key(m.group(1)), set()).add(
            m.group(2).strip('"').lower())
    # A migration may also create brand-new tables.
    for t, cols in baseline_columns(sql).items():
        known.setdefault(t, set()).update(cols)


# Statements that need the column to already exist.
_REQUIRES_COLUMN = [
    (re.compile(r"ALTER\s+TABLE\s+(?:ONLY\s+)?([\w.\"]+)\s+ALTER\s+COLUMN\s+([\w\"]+)",
                re.I), "ALTER COLUMN"),
    (re.compile(r"ALTER\s+TABLE\s+(?:ONLY\s+)?([\w.\"]+)\s+RENAME\s+COLUMN\s+([\w\"]+)",
                re.I), "RENAME COLUMN"),
    (re.compile(r"ALTER\s+TABLE\s+(?:ONLY\s+)?([\w.\"]+)\s+DROP\s+COLUMN\s+(?!IF\s+EXISTS)([\w\"]+)",
                re.I), "DROP COLUMN (no IF EXISTS)"),
]


def main() -> int:
    if not os.path.isdir(MIGRATIONS):
        print(f"[check-migrations-fresh-install] no {MIGRATIONS} dir — nothing to check.")
        return 0
    files = sorted(f for f in os.listdir(MIGRATIONS) if f.endswith(".sql"))
    if BASELINE not in files:
        print(f"[check-migrations-fresh-install] WARN — {BASELINE} not found; "
              "cannot prove fresh-install safety.")
        return 0

    with open(os.path.join(MIGRATIONS, BASELINE), encoding="utf-8") as fh:
        known = baseline_columns(fh.read())

    problems = []
    for fname in [f for f in files if f != BASELINE]:
        with open(os.path.join(MIGRATIONS, fname), encoding="utf-8") as fh:
            sql = fh.read()
        for pattern, kind in _REQUIRES_COLUMN:
            for m in pattern.finditer(_strip_do_blocks(sql)):
                table, col = _table_key(m.group(1)), m.group(2).strip('"').lower()
                if table not in known:
                    continue                      # unknown table — can't prove absence
                if col not in known[table]:
                    problems.append((fname, kind, table, col))
        added_columns(sql, known)                 # later files may rely on these

    if problems:
        print("[check-migrations-fresh-install] FAIL — these statements break a "
              "FIRST-TIME install (the column does not exist on a fresh database, so "
              "init_db aborts and the agent boot-loops):")
        for fname, kind, table, col in problems:
            print(f"  {fname}: {kind} {table}.{col} — not created by {BASELINE} "
                  "nor added by an earlier migration")
        print("  FIX: guard it (wrap in `DO $$ ... $$;` that checks "
              "information_schema.columns first, or use IF EXISTS), or delete the "
              "statement if a later migration removes the column anyway.")
        return 1

    print(f"[check-migrations-fresh-install] OK — {len(files)} migration(s); every "
          "column-dependent statement is either satisfied by the baseline or guarded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
