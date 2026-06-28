"""Bound test for spec platform.docs.pi-setup-nvme-swap (issue #45).

Asserts docs/00-pi-hardware-and-setup.md documents the operator's target state —
a 16 GB Pi 5 with an M.2 2242 NVMe, booting off the NVMe, plus 2 GB zram and 6 GB
persistent on-disk swap — each as a runnable command block, with a Jeff Geerling
reference. This is exactly the Validation the operator specified in the issue.

Deterministic + offline: reads the doc file only.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DOC = REPO / "docs" / "00-pi-hardware-and-setup.md"


def _lines_with(text, needle):
    return [ln for ln in text.splitlines() if needle.lower() in ln.lower()]


class TestPiSetupDoc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text(encoding="utf-8")
        cls.low = cls.text.lower()
        cls.bash_blocks = re.findall(r"```bash\n.*?```", cls.text, re.DOTALL)

    # (1) 16 GB is the RECOMMENDATION (scoped negative: old 8GB framing gone)
    def test_recommends_16gb(self):
        self.assertNotIn("8 GB** (16 GB better)", self.text)
        self.assertNotIn("8 GB is the practical floor", self.text)
        pi_rows = _lines_with(self.text, "Raspberry Pi 5,")
        self.assertTrue(pi_rows, "no Pi shopping-list row found")
        pi_row = pi_rows[0].lower()
        self.assertIn("16 gb", pi_row)
        self.assertIn("recommend", pi_row)

    # (2) 2242 form factor; the SSD shopping row must not recommend buying a 2280
    def test_2242_not_2280(self):
        self.assertIn("2242", self.text)
        ssd_rows = _lines_with(self.text, "NVMe SSD, 256")
        self.assertTrue(ssd_rows, "no SSD shopping-list row found")
        self.assertNotIn("2280", ssd_rows[0], "SSD row must not recommend a 2280 drive")
        # a prominent warning that calls out 2242 vs the common 2280
        warning = [ln for ln in self.text.splitlines()
                   if ln.lstrip().startswith(">") and "2242" in ln and "2280" in ln]
        self.assertTrue(warning, "expected a prominent 2242-not-2280 warning callout")

    # (3) Jeff Geerling reference
    def test_geerling_reference(self):
        self.assertIn("geerling", self.low)

    # (4) NVMe boot: the added EEPROM update + explicit BOOT_ORDER + a root-on-nvme verify
    def test_nvme_boot_commands(self):
        self.assertIn("rpi-eeprom-update", self.text)
        self.assertIn("BOOT_ORDER", self.text)
        self.assertTrue("findmnt" in self.text or "nvme0n1" in self.text)

    # (5) 2 GB zram with PERCENT disabled so SIZE=2048 actually yields 2 GB
    def test_zram_2gb(self):
        self.assertIn("zram", self.low)
        self.assertIn("SIZE=2048", self.text)
        self.assertIn("zramswap", self.low)
        self.assertTrue("#PERCENT" in self.text or "overrides" in self.low,
                        "must disable/flag PERCENT (it overrides SIZE)")

    # (6) 6 GB persistent on-disk swap (manual primary; dphys alternative), with verify
    def test_6gb_disk_swap(self):
        has_manual = "fallocate -l 6g" in self.low
        has_dphys = "dphys-swapfile" in self.low and "6144" in self.text
        self.assertTrue(has_manual or has_dphys, "no 6 GB on-disk swap procedure")
        self.assertTrue("/etc/fstab" in self.text or "dphys-swapfile" in self.low,
                        "on-disk swap must be made persistent")
        self.assertTrue("swapon --show" in self.text or "swapon -s" in self.text,
                        "must show how to verify swap")

    # (7) the swap procedures are in runnable fenced bash blocks
    def test_swap_in_fenced_bash(self):
        self.assertTrue(any("zramswap" in b for b in self.bash_blocks),
                        "zram setup must be in a fenced bash block")
        self.assertTrue(any(("fallocate -l 6G" in b) or ("dphys-swapfile setup" in b)
                            for b in self.bash_blocks),
                        "6 GB swap setup must be in a fenced bash block")
        self.assertGreaterEqual(len(self.bash_blocks), 4)


if __name__ == "__main__":
    unittest.main()
