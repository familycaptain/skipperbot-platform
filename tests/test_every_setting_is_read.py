"""Every setting Skipper offers is read by something.

A field in Settings that nothing reads is worse than no field: it looks like a control, the
household changes it, and nothing happens. Six were found in one pass —
smart_model / dumb_model ("Takes effect immediately"), embedding_model (warned of a restart and
re-embedding), realtime_model (voice read an env var instead), max_session_turns (never wired),
and the per-app enhance_model / intelligence_extraction_model, left behind when their calls moved
to the model tiers. One had even had its wording corrected (ev-78) without anyone noticing it was
dead.

This declares a setting dead if its key does not appear as a quoted string anywhere in product
code other than the place that declares it — the platform tree and every skipperbot-app-* repo
checked out beside it. A setting read through a key built at runtime (f"tier_{t}_model") must be
listed in DYNAMIC, with where it is read.

Run: python3 -m unittest tests.test_every_setting_is_read
"""
import ast
import glob
import os
import re
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(ROOT)
_SKIP = {"tests", "node_modules", ".git", "__pycache__", "dist", "specs", "specs-audit", "private"}

# key -> where it is read, for keys only ever read via a runtime-built name.
DYNAMIC: dict = {}


def _repos():
    return [ROOT] + sorted(glob.glob(os.path.join(PARENT, "skipperbot-app-*")))


def _declared():
    out = []   # (key, declaring file)
    routes = os.path.join(ROOT, "apps", "settings", "routes.py")
    with open(routes, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            d = {k.value: v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant)}
            if "key" in d and "type" in d and isinstance(d["key"], ast.Constant):
                out.append((d["key"].value, routes))
    manifests = glob.glob(os.path.join(ROOT, "apps", "*", "manifest.yaml"))
    for repo in _repos()[1:]:
        manifests += glob.glob(os.path.join(repo, "manifest.yaml"))
    for m in manifests:
        with open(m, encoding="utf-8") as fh:
            y = yaml.safe_load(fh) or {}
        for c in (y.get("config") or []):
            if isinstance(c, dict) and c.get("key"):
                out.append((c["key"], m))
    return out


def _corpus():
    src = {}
    for repo in _repos():
        for dp, dn, fns in os.walk(repo):
            dn[:] = [d for d in dn if d not in _SKIP]
            for f in fns:
                if f.endswith((".py", ".jsx", ".js")):
                    p = os.path.join(dp, f)
                    try:
                        with open(p, encoding="utf-8") as fh:
                            src[p] = fh.read()
                    except (UnicodeDecodeError, OSError):
                        pass
    return src


class EverySettingIsRead(unittest.TestCase):
    def test_no_setting_is_declared_without_a_reader(self):
        corpus = _corpus()
        dead = []
        for key, decl in _declared():
            if key in DYNAMIC:
                continue
            pat = re.compile(r"""(["'])""" + re.escape(key) + r"""\1""")
            if not any(p != decl and pat.search(s) for p, s in corpus.items()):
                dead.append(f"{key}  (declared in {os.path.relpath(decl, PARENT)})")
        self.assertEqual(dead, [], "settings nothing reads — remove them, wire them, or list a "
                                   "runtime-built reader in DYNAMIC")

    def test_the_scan_sees_the_settings_it_should(self):
        # Guards the guard: if parsing silently found nothing, the test above would pass vacuously.
        keys = {k for k, _ in _declared()}
        self.assertGreater(len(keys), 40)
        self.assertIn("realtime_model", keys)      # platform panel
        self.assertIn("default_channels", keys)    # an app manifest


if __name__ == "__main__":
    unittest.main()
