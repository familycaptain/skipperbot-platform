"""Bound test for spec platform.deploy.agent-memory-containment (issue #96).

The docker-compose `agent` service must declare a defensive, env-overridable memory
cap (a TRUE RAM ceiling), a runaway-friendly restart policy, and the glibc arena
cap — plus a Pi cgroup-memory prerequisite so the cap isn't a silent no-op. These
are deterministic file-parse assertions (no container run); the enforced-limit
oracle runs at validate-time on the test host (`docker inspect`).

Run with ``python3 -m unittest tests.evolve.deploy.test_agent_memory_containment``.
"""

import unittest
from pathlib import Path

import yaml

REPO = Path(__import__("repo_paths").ROOT)

# The operator constraint: the cap is overridable WITHOUT editing this tracked file
# via compose env interpolation, defaulting to 6g.
MEM = "${AGENT_MEM_LIMIT:-6g}"


class AgentMemoryContainment(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
        cls.agent = cls.compose["services"]["agent"]

    def test_mem_limit_is_env_overridable_default_6g(self):
        self.assertEqual(
            self.agent.get("mem_limit"), MEM,
            "agent.mem_limit must be the env-interpolated ${AGENT_MEM_LIMIT:-6g} "
            "(overridable without editing the tracked compose file)",
        )

    def test_memswap_equals_mem_limit_true_ram_ceiling(self):
        self.assertEqual(
            self.agent.get("memswap_limit"), MEM,
            "agent.memswap_limit must equal mem_limit so the cap is a TRUE RAM "
            "ceiling (else Docker allows 2x in swap)",
        )

    def test_restart_is_unless_stopped(self):
        self.assertEqual(
            self.agent.get("restart"), "unless-stopped",
            "agent.restart must be 'unless-stopped' (auto-restart a runaway, respect docker stop)",
        )

    def test_malloc_arena_max_set(self):
        env = self.agent.get("environment", {})
        # environment may be a dict or a list of KEY=VALUE strings
        if isinstance(env, list):
            env = dict(e.split("=", 1) for e in env if "=" in e)
        self.assertEqual(str(env.get("MALLOC_ARENA_MAX")), "2")

    def test_cgroup_prerequisite_referenced(self):
        """A compose comment must point at the Pi cgroup prerequisite so the cap
        can't be a silent no-op, and the Pi doc must document enabling it."""
        compose_text = (REPO / "docker-compose.yml").read_text().lower()
        self.assertIn("cgroup", compose_text,
                      "compose must comment the cgroup-memory prerequisite near the mem_limit")

        pi_doc = (REPO / "docs" / "00-pi-hardware-and-setup.md").read_text()
        self.assertIn("cgroup_enable=memory", pi_doc)
        self.assertIn("cgroup_memory=1", pi_doc)
        self.assertIn("cmdline.txt", pi_doc)

    def test_only_agent_is_capped(self):
        """The cap is scoped to the agent service (db is untouched)."""
        db = self.compose["services"].get("db", {})
        self.assertIsNone(db.get("mem_limit"), "db service must not be capped by this change")


if __name__ == "__main__":
    unittest.main()
