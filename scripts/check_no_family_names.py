"""
check_no_family_names.py — CI guard.

Fails the build if any forbidden identifier is found in source files. Used
to prevent family names, hardcoded timezones, or legacy placeholders from
leaking into a public release.

Usage:
    python scripts/check_no_family_names.py
    python scripts/check_no_family_names.py --paths path1 path2

Exit code 0 = clean. Exit code 1 = at least one forbidden string found
(also prints the offending file:line:context).

This runs in CI on every PR. Local devs should run it before pushing.

Configuration: the forbidden-strings list is below. To intentionally
allow a hit (e.g. a placeholder name used in test fixtures), wrap the
usage in `# noqa: family-name` or list the file in EXCLUDED_FILES.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Forbidden strings. Lowercase comparison. Two tiers, because a single
# word-boundary check used to miss names fused into identifiers/URLs/ids
# (`kid-jacob000`, `ATTUNE_GOAL`, `attunewiki.com`) — that gap let real leaks
# ship. Use `# noqa: family-name` on a line for an intentional exception.

# Real-household identifiers — matched ANYWHERE, including as a substring of a
# larger token (ids, slugs, URLs, snake_case/CamelCase identifiers). These
# strings essentially never occur legitimately in public source.
FORBIDDEN_NAMES_SUBSTRING = [
    "rodney",
    "jessica",
    "jacob",
    "elijah",
    "caleb",
    "attune",
    "burton",
    "burtonhome",
]

# Legacy obfuscated placeholders — matched on whole-word boundaries only,
# because they collide with real words and Bible book names (Micah, Joel) and
# would false-positive under substring matching. Clean these up and replace
# with generic placeholders (alice, bob, user1, kid1).
FORBIDDEN_NAMES_WORD = [
    "janelle",
    "maggie",
    "micah",
    "joel",
]

FORBIDDEN_TIMEZONES = [
    "America/Chicago",
    "US/Central",
    "CST",
    "CDT",
]

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".security",
    "logs",
    "backups",
    "uploads",
    "tmp",
}

# Files that may legitimately contain the forbidden strings (e.g. CHANGELOG
# may reference a historical event, scripts/check_no_family_names.py itself).
EXCLUDED_FILES = {
    "scripts/check_no_family_names.py",
    "CHANGELOG.md",
}

# Extensions we scan. Everything else is skipped.
SCAN_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".sql", ".md",
                   ".yaml", ".yml", ".json", ".toml", ".sh", ".ps1", ".bat"}


def _word_pattern(words: list[str]) -> re.Pattern[str]:
    escaped = [re.escape(w) for w in words]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


def _substring_pattern(words: list[str]) -> re.Pattern[str]:
    escaped = [re.escape(w) for w in words]
    return re.compile("(" + "|".join(escaped) + ")", re.IGNORECASE)


def scan_path(root: Path) -> list[tuple[Path, int, str, str]]:
    findings: list[tuple[Path, int, str, str]] = []
    # Real names: match anywhere (catches `kid-jacob000`, `ATTUNE_GOAL`, …).
    substring_pattern = _substring_pattern(FORBIDDEN_NAMES_SUBSTRING)
    # Collision-prone placeholders + timezone strings: whole-word only, to
    # avoid false positives like "CST" inside "DOCSTRING" or "Micah" the book.
    word_pattern = _word_pattern(FORBIDDEN_NAMES_WORD)
    tz_pattern = _word_pattern(FORBIDDEN_TIMEZONES)

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if str(rel).replace("\\", "/") in EXCLUDED_FILES:
            continue
        if path.suffix not in SCAN_EXTENSIONS:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if "noqa: family-name" in line:
                continue
            for match in substring_pattern.finditer(line):
                findings.append((rel, lineno, match.group(0), line.strip()))
            for match in word_pattern.finditer(line):
                findings.append((rel, lineno, match.group(0), line.strip()))
            for match in tz_pattern.finditer(line):
                findings.append((rel, lineno, match.group(0), line.strip()))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", nargs="*", default=["."])
    args = parser.parse_args()

    total_findings: list[tuple[Path, int, str, str]] = []
    for root_str in args.paths:
        root = Path(root_str).resolve()
        total_findings.extend(scan_path(root))

    if not total_findings:
        print("OK — no forbidden strings found.")
        return 0

    print(f"FAIL — {len(total_findings)} forbidden string(s) found:")
    for path, lineno, match, line in total_findings:
        print(f"  {path}:{lineno}: '{match}' in: {line[:120]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
