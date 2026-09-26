"""Finishing a task ticks the Trello card's own "Mark Complete", not just moves the card.

iss-45be781a (Elijah): "when a Skipper task is completed, make sure that the 'Mark Complete' toggle
on the Trello task is checked 'Complete', so that the due date doesn't stay active and become
overdue when it is supposed to be not."

Completing a task moved its card to the Done list and stopped there. Trello's completion checkbox
(dueComplete) is a separate field; left unticked, the due date stays live on the board and goes
overdue for work that is finished. Nothing in the platform ever wrote it — it was only read.

Run: python3 -m unittest tests.platform.test_trello_mark_complete
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import trello_task_sync as tts  # noqa: E402

TASK = {"id": "t-1", "trello_card_id": "card-9"}
PROJECT = {"id": "p-1"}
CONFIG = {"board": "Family", "done_list": "Done"}


class Completing(unittest.TestCase):
    def _complete(self, move_result="Moved card to 'Done'."):
        sent = []
        with mock.patch.object(tts, "get_project_trello_config", return_value=CONFIG), \
             mock.patch.object(tts, "move_card_to_list", return_value=move_result), \
             mock.patch("trello_client._board_request",
                        side_effect=lambda m, path, board, params: sent.append((m, path, params)) or {}):
            tts.sync_task_completion_to_trello(TASK, PROJECT)
        return sent

    def test_it_ticks_mark_complete(self):
        sent = self._complete()
        self.assertIn(("PUT", "/cards/card-9", {"dueComplete": "true"}), sent)

    def test_it_still_ticks_it_when_the_move_to_done_fails(self):
        # e.g. the board has no Done list — the due date should still stop.
        sent = self._complete(move_result="Error: no list named Done")
        self.assertIn(("PUT", "/cards/card-9", {"dueComplete": "true"}), sent)


class Reopening(unittest.TestCase):
    def test_set_card_complete_false_clears_it(self):
        sent = []
        with mock.patch.object(tts, "get_project_trello_config", return_value=CONFIG), \
             mock.patch("trello_client._board_request",
                        side_effect=lambda m, path, board, params: sent.append(params) or {}):
            out = tts.set_card_complete(TASK, PROJECT, False)
        self.assertEqual(sent, [{"dueComplete": "false"}])
        self.assertEqual(out, "Marked not complete.")

    def test_reopening_a_task_clears_it(self):
        # A task that is live again must not keep its due date disarmed on the board.
        with open(os.path.join(ROOT, "apps/goals/store.py"), encoding="utf-8") as fh:
            src = fh.read()
        block = src[src.index("# 3b. Trello: status changes"):src.index("# 3c. Trello")]
        self.assertIn("set_card_complete(item, proj, False)", block)
        self.assertIn('("not_started", "in_progress")', block)


class NoLinkNoCall(unittest.TestCase):
    def test_an_unlinked_task_makes_no_call(self):
        with mock.patch.object(tts, "get_project_trello_config", return_value=CONFIG), \
             mock.patch("trello_client._board_request") as req:
            out = tts.set_card_complete({"id": "t-2"}, PROJECT, True)
        req.assert_not_called()
        self.assertTrue(out.startswith("Error"))


class TheClientCanWriteIt(unittest.TestCase):
    def test_update_card_accepts_due_complete(self):
        import trello_client
        with mock.patch.object(trello_client, "_find_card", return_value={"id": "c", "name": "n"}), \
             mock.patch.object(trello_client, "_board_request",
                               return_value={"id": "c", "name": "n"}) as req:
            trello_client.update_card("Family", "", card_id="c", due_complete=True)
        self.assertEqual(req.call_args.args[3], {"dueComplete": "true"})


if __name__ == "__main__":
    unittest.main()
