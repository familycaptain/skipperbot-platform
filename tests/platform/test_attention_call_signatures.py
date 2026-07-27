"""The attention path's calls must match the signatures they call.

Chat went down entirely with `log_inbound_message() got an unexpected keyword argument
'event_id'`. The attention concurrency fix updated the CALLER and the function BODY — which
reads `event_id` — but not the parameter list in between. Every inbound chat message died
at the first line of work, on every surface, for every user.

758 tests were green at the time. Nothing exercised the seam, because each side was
individually plausible: the caller looked right, the body looked right, and only the two
together were wrong.

So this pins the seam rather than the behaviour: the keywords `submit_message` passes must
be accepted by `log_inbound_message`, and what that function forwards must be accepted by
`log_event`. A half-applied edit to any of the three now fails here.
"""
import ast
import inspect
import os
import sys
import unittest
from unittest import mock


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


REPO = _repo_root()
sys.path.insert(0, REPO)


def _accepts(fn, kwargs):
    """Would fn(**kwargs) bind? Returns the offending name, or None."""
    sig = inspect.signature(fn)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return None
    for name in kwargs:
        if name not in sig.parameters:
            return name
    return None


class TheInboundLoggingSeamHolds(unittest.TestCase):
    def setUp(self):
        # consciousness reaches the DB at call time, not import time, so importing is safe;
        # stub the query layer for the forwarding test below.
        self.mods = {}
        for name in ("data_layer.db",):
            self.mods[name] = sys.modules.get(name)

    def test_log_inbound_message_accepts_what_submit_message_passes(self):
        from app_platform import consciousness
        # These are the keywords app_platform/attention.py::submit_message passes.
        passed = {"who_from": "x", "content": "y", "surface": "chat", "event_id": "cl-1"}
        bad = _accepts(consciousness.log_inbound_message, passed)
        self.assertIsNone(bad, f"log_inbound_message does not accept {bad!r}")

    def test_the_caller_and_the_signature_have_not_drifted(self):
        # Read the ACTUAL call site rather than trusting the list above to stay current.
        with open(os.path.join(REPO, "app_platform/attention.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and any(kw.arg == "who_from" for kw in n.keywords)]
        self.assertTrue(calls, "expected an inbound-logging call in attention.py")
        from app_platform import consciousness
        for call in calls:
            names = {kw.arg for kw in call.keywords if kw.arg}
            bad = _accepts(consciousness.log_inbound_message, dict.fromkeys(names))
            self.assertIsNone(bad, f"attention.py passes {bad!r}, which log_inbound_message "
                                   f"does not accept")

    def test_every_name_the_body_reads_is_actually_bound(self):
        # The specific failure: the body read `event_id` while nothing defined it. A
        # parameter removed from the signature but left in the body reads as fine in
        # review and explodes at runtime.
        with open(os.path.join(REPO, "app_platform/consciousness.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "log_inbound_message")
        params = {a.arg for a in fn.args.kwonlyargs} | {a.arg for a in fn.args.args}
        assigned = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        # Only check names forwarded as keyword arguments — module-level helpers are
        # legitimately free.
        forwarded = {kw.arg for n in ast.walk(fn) if isinstance(n, ast.Call)
                     for kw in n.keywords if kw.arg and isinstance(kw.value, ast.Name)}
        reads = {kw.value.id for n in ast.walk(fn) if isinstance(n, ast.Call)
                 for kw in n.keywords if kw.arg and isinstance(kw.value, ast.Name)}
        for name in reads & (forwarded | {"event_id"}):
            if name in ("SKIPPER",):
                continue
            with self.subTest(name=name):
                self.assertTrue(name in params or name in assigned,
                                f"body forwards {name!r} but nothing binds it")

    def test_it_forwards_the_caller_supplied_id_through_to_the_row(self):
        # The id has to survive the hop: attention registers interest under it BEFORE the
        # row exists, so a different id there means the caller waits out the full timeout
        # on a reply that was in fact delivered.
        from app_platform import consciousness
        with mock.patch.object(consciousness, "fetch_one", return_value=None), \
             mock.patch.object(consciousness, "log_event") as log_event:
            consciousness.log_inbound_message(
                who_from="rodney", content="hello", surface="chat", event_id="cl-abc123")
        log_event.assert_called_once()
        self.assertEqual(log_event.call_args.kwargs.get("event_id"), "cl-abc123")

    def test_log_event_accepts_what_log_inbound_message_forwards(self):
        from app_platform import consciousness
        forwarded = {"kind": "message", "who_from": "x", "who_to": "y", "domain": "chat",
                     "surface": "chat", "content": "z", "reply_to": None, "thread_id": None,
                     "payload": None, "needs_attention": True, "event_id": "cl-1"}
        bad = _accepts(consciousness.log_event, forwarded)
        self.assertIsNone(bad, f"log_event does not accept {bad!r}")


if __name__ == "__main__":
    unittest.main()
