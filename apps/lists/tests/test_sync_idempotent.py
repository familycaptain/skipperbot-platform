"""Bound test for lists.trello-boards.sync-list (issue #24).

A no-op Trello poll (same cards, only dateLastActivity moved) must write NOTHING and not
bump last_sync, so the ~30s poller stops churning memory; a real change still re-saves.

Pure-stdlib (no DB/network): the apps.lists.store import chain is stubbed at the leaves
(mirrors the weather bound-test pattern), and the DB read/write seams are patched.
"""
import logging
import sys
import types
import unittest
from unittest import mock


def _stub(name, **attrs):
    if name not in sys.modules:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m


_stub("config", logger=logging.getLogger("test"))
_stub("app_platform.time", get_timezone=lambda user_id=None: None)
_stub("auto_memory", log_entity_change=lambda *a, **k: None)
_stub("apps.lists.data")  # _dl_lists; _load_list/_save_list are patched so its members aren't called
_stub("trello_client", get_cards=lambda *a, **k: [])

from apps.lists import store  # noqa: E402


def _card(cid, name, activity="2026-01-01T00:00:00Z"):
    return {"id": cid, "name": name, "dateLastActivity": activity, "closed": False}


def _item(cid, text, **over):
    base = {"id": "li-" + cid, "text": text, "trello_card_id": cid,
            "archived": False, "added_by": "trello_sync", "added_at": "x"}
    base.update(over)
    return base


def _list(items):
    return {"id": "l1", "name": "Lowes", "items": list(items),
            "trello": {"board": "shopping", "list_name": "Lowes",
                       "last_sync": "2026-06-18T19:33:26-05:00", "track_items": False}}


class SignatureTests(unittest.TestCase):
    def test_added_at_ignored(self):
        a = [_item("c1", "Milk")]
        b = [_item("c1", "Milk", added_at="DIFFERENT")]
        self.assertEqual(store._list_item_signature(a), store._list_item_signature(b))

    def test_rename_detected(self):
        self.assertNotEqual(store._list_item_signature([_item("c1", "Milk")]),
                            store._list_item_signature([_item("c1", "Bread")]))

    def test_reorder_detected(self):
        a = [_item("c1", "Milk"), _item("c2", "Eggs")]
        b = [_item("c2", "Eggs"), _item("c1", "Milk")]
        self.assertNotEqual(store._list_item_signature(a), store._list_item_signature(b))

    def test_archived_excluded(self):
        active = [_item("c1", "Milk")]
        with_arch = active + [_item("c2", "Old", archived=True)]
        self.assertEqual(store._list_item_signature(active),
                         store._list_item_signature(with_arch))


class SyncIdempotentTests(unittest.TestCase):
    def setUp(self):
        self.saved = []
        mock.patch.object(store, "_save_list", side_effect=self.saved.append).start()
        mock.patch.object(store, "_trello_enabled", return_value=True).start()
        mock.patch.object(store, "_now_iso", return_value="2026-06-19T10:00:00-05:00").start()

    def tearDown(self):
        mock.patch.stopall()

    def _cards(self, cards):
        sys.modules["trello_client"].get_cards = lambda *a, **k: cards

    def test_first_sync_saves(self):
        lst = _list([])
        with mock.patch.object(store, "_load_list", return_value=lst):
            self._cards([_card("c1", "Milk")])
            store.sync_from_trello("l1")
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(lst["trello"]["last_sync"], "2026-06-19T10:00:00-05:00")

    def test_noop_sync_does_not_save_or_bump(self):
        lst = _list([_item("c1", "Milk")])
        prev = lst["trello"]["last_sync"]
        with mock.patch.object(store, "_load_list", return_value=lst):
            self._cards([_card("c1", "Milk", activity="2099-12-31T00:00:00Z")])
            store.sync_from_trello("l1")
        self.assertEqual(self.saved, [])
        self.assertEqual(lst["trello"]["last_sync"], prev)

    def test_change_saves(self):
        lst = _list([_item("c1", "Milk")])
        with mock.patch.object(store, "_load_list", return_value=lst):
            self._cards([_card("c1", "Milk"), _card("c2", "Eggs")])
            store.sync_from_trello("l1")
        self.assertEqual(len(self.saved), 1)

    def test_fetch_error_does_not_save(self):
        lst = _list([_item("c1", "Milk")])

        def boom(*a, **k):
            raise RuntimeError("trello down")

        with mock.patch.object(store, "_load_list", return_value=lst):
            sys.modules["trello_client"].get_cards = boom
            out = store.sync_from_trello("l1")
        self.assertEqual(self.saved, [])
        self.assertIn("Error", out)

    def test_real_emptying_saves(self):
        lst = _list([_item("c1", "Milk")])
        with mock.patch.object(store, "_load_list", return_value=lst):
            self._cards([])
            store.sync_from_trello("l1")
        self.assertEqual(len(self.saved), 1)


if __name__ == "__main__":
    unittest.main()
