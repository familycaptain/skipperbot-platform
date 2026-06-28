"""Bound test for spec platform.docs.evolve-plug (issue #50).

Asserts the platform authoring docs introduce + link the standalone Evolve SDLC
engine: docs/BUILDING_APPS.md has an "Expand Skipper with Evolve" section that
frames it as a way to extend Skipper with the same patterns, describes its gated
SDLC nature, disambiguates it as a standalone engine (not an installable app),
and links the repo; docs/02-adding-apps.md cross-links it. Assertions are scoped
to the Evolve section span and are case/synonym tolerant.

Deterministic + offline: reads the doc files only.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BUILDING = REPO / "docs" / "BUILDING_APPS.md"
ADDING = REPO / "docs" / "02-adding-apps.md"
REPO_URL = "github.com/familycaptain/evolve"


def _evolve_section(text):
    """The span from the first '##+ ...evolve...' heading to the next '## ' heading."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^#{2,}\s.*evolve", ln, re.IGNORECASE):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


class TestEvolvePlugDoc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.building = BUILDING.read_text(encoding="utf-8")
        cls.adding = ADDING.read_text(encoding="utf-8")
        cls.section = _evolve_section(cls.building)

    def test_evolve_section_exists(self):
        self.assertIsNotNone(self.section, "BUILDING_APPS.md needs an Evolve section heading")

    def test_repo_url_in_section(self):
        self.assertIn(REPO_URL, self.section)

    def test_expand_same_patterns_framing(self):
        low = self.section.lower()
        self.assertTrue(re.search(r"expand|extend", low), "must frame Evolve as expanding/extending Skipper")
        self.assertTrue(re.search(r"same|pattern|process|approach|rigor|methodology", low),
                        "must frame it as the same patterns/process Skipper was built with")

    def test_gated_sdlc_cue(self):
        # distinctive cues — NOT the file-common bare word 'spec'
        low = self.section.lower()
        self.assertTrue(re.search(r"gate|sdlc|triage|worktree|validation|reviewed|gated", low),
                        "must convey Evolve's gated/reviewed SDLC nature")

    def test_standalone_disambiguation(self):
        low = self.section.lower()
        self.assertTrue(
            ("standalone" in low) or ("run it yourself" in low) or ("run yourself" in low)
            or ("not a skipper app" in low) or ("own repo" in low),
            "must disambiguate Evolve as a standalone engine you run yourself, not an installable app")

    def test_02_cross_links_evolve(self):
        # a single line containing both 'Evolve' and a link to BUILDING_APPS or the repo URL
        for ln in self.adding.splitlines():
            if "evolve" in ln.lower() and ("BUILDING_APPS.md" in ln or REPO_URL in ln):
                return
        self.fail("docs/02-adding-apps.md must cross-link the Evolve section (Evolve + a link on one line)")


if __name__ == "__main__":
    unittest.main()
