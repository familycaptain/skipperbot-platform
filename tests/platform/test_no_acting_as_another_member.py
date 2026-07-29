"""You cannot ask the platform to act as somebody else.

Three endpoints took the acting identity from the REQUEST BODY:

* `/chat` — any signed-in caller could speak as anyone. The WebSocket path always used the
  principal; only the HTTP fallback was exposed.
* `/api/mobile/register` — a device token could be registered under another person's name,
  pointing their urgent pushes at your phone.
* `/api/voice/session` — a session could be opened under another member's identity, with
  their instructions, tools and data.

This is NOT covered by the household's mutual-trust rule. That rule says an adult may read
and change another adult's records. Speaking AS them is a different act: it writes words
into the shared append-only record attributed to a person who did not say them, and recall,
the console and the PM sweep then treat those words as theirs.

The one deliberate exception is the shared speaker's stand-in identity. It belongs to
nobody, so passing it on impersonates nobody, and anything person-specific is already
refused under it. Keeping it working is what lets "what's the weather" answer at the
kitchen speaker while "add to my list" does not.
"""
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

ROSTER = {"rodney": {"name": "rodney", "role": "admin"},
          "jacob": {"name": "jacob", "role": "member"}}


def _read_agent():
    with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
        return fh.read()


class _Req:
    """Just enough Request for the helper: a principal and a path."""

    def __init__(self, name):
        self.state = mock.MagicMock()
        self.state.principal = {"name": name, "role": "member"} if name else None
        self.url = mock.MagicMock()
        self.url.path = "/test"


class _Refused(Exception):
    """Stand-in for fastapi's HTTPException, so this runs without the web framework."""

    def __init__(self, status_code=None, detail=""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _helper():
    """Load _claimed_actor without importing agent.py (which needs the whole runtime).

    Compiled from the real source, so the test cannot drift from the code it guards.
    """
    import ast
    import types
    tree = ast.parse(_read_agent())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_claimed_actor")
    mod = types.ModuleType("shim")
    mod.__dict__.update({
        "HTTPException": _Refused,
        "Request": object,          # the signature annotation is evaluated at def time
        "logger": mock.MagicMock(),
        "_principal": lambda r: getattr(r.state, "principal", None),
    })
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<shim>", "exec"), mod.__dict__)
    return mod._claimed_actor, _Refused


class ClaimingSomebodyElseIsRefused(unittest.TestCase):
    def setUp(self):
        self.claimed_actor, self.HTTPException = _helper()
        users = mock.MagicMock()
        users.get_user.side_effect = lambda n: ROSTER.get((n or "").lower().strip())
        self.patch = mock.patch.dict(sys.modules, {"data_layer.users": users})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_claiming_another_real_member_is_403(self):
        with self.assertRaises(self.HTTPException) as ctx:
            self.claimed_actor(_Req("jacob"), "rodney")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_claiming_another_member_is_403_even_where_placeholders_are_allowed(self):
        # The voice exception must not become a general impersonation hole.
        with self.assertRaises(self.HTTPException) as ctx:
            self.claimed_actor(_Req("jacob"), "rodney", allow_placeholder=True)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_claiming_yourself_is_fine(self):
        self.assertEqual(self.claimed_actor(_Req("jacob"), "jacob"), "jacob")
        self.assertEqual(self.claimed_actor(_Req("jacob"), "  JACOB "), "jacob")

    def test_claiming_nothing_falls_back_to_the_principal(self):
        self.assertEqual(self.claimed_actor(_Req("jacob"), ""), "jacob")
        self.assertEqual(self.claimed_actor(_Req("jacob"), None), "jacob")

    def test_a_stand_in_is_refused_where_placeholders_are_not_allowed(self):
        with self.assertRaises(self.HTTPException):
            self.claimed_actor(_Req("jacob"), "user1")

    def test_a_stand_in_is_allowed_for_the_shared_speaker(self):
        # Nobody owns it, so nobody is impersonated — and the tool layer refuses anything
        # person-specific under it.
        self.assertEqual(self.claimed_actor(_Req("jacob"), "user1", allow_placeholder=True),
                         "user1")

    def test_an_unverifiable_roster_refuses_rather_than_guessing(self):
        # Here, unlike the tool gate, failing open would mean ALLOWING an impersonation.
        users = mock.MagicMock()
        users.get_user.side_effect = RuntimeError("db down")
        with mock.patch.dict(sys.modules, {"data_layer.users": users}):
            with self.assertRaises(self.HTTPException) as ctx:
                self.claimed_actor(_Req("jacob"), "someone", allow_placeholder=True)
        self.assertEqual(ctx.exception.status_code, 403)


class TheThreeEndpointsUseIt(unittest.TestCase):
    """Pin the call sites: the helper is useless if an endpoint stops calling it."""

    def _body(self, marker, span=900):
        src = _read_agent()
        start = src.index(marker)
        return src[start:start + span]

    def test_chat_takes_the_speaker_from_the_principal(self):
        body = self._body('async def chat(request: ChatRequest')
        self.assertIn("_claimed_actor(http_request, request.user_id)", body)
        self.assertNotIn("process_chat(request.user_id", body)

    def test_mobile_register_binds_the_device_to_the_caller(self):
        body = self._body("async def mobile_register(")
        self.assertIn("_claimed_actor(http_request, request.user_id)", body)
        self.assertNotIn("user_id=request.user_id", body)

    def test_voice_session_allows_only_the_stand_in(self):
        body = self._body("async def voice_create_session(")
        self.assertIn("allow_placeholder=True", body)
        self.assertNotIn("mint_ephemeral_token, request.user_id", body)

    def test_the_websocket_path_still_uses_the_principal(self):
        # It was always correct; this fix must not have disturbed it.
        src = _read_agent()
        self.assertIn('user_id = principal["name"]', src)


if __name__ == "__main__":
    unittest.main()
