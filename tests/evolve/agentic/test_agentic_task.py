"""#109 — autonomous scheduled tasks. A task = a schedule (job_config spec) + a
d-* prompt doc + the `agentic` job type. The handler runs the prompt with the
SAME tools a chat turn has (no artificial limits) — if the prompt says to notify
someone, it uses the ordinary notification tools. Manageable from chat and the
Schedules app. (End-to-end run verified live on the test box.)

Run: python -m unittest tests.evolve.agentic.test_agentic_task
"""
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class AgenticTask(unittest.TestCase):
    def test_manifest_registers_agentic_job_type(self):
        m = _read("apps/agentic/manifest.yaml")
        self.assertIn("type: agentic", m)
        self.assertIn("handler: agentic.handle_agentic", m)

    def test_create_tool_builds_doc_schedule_and_config(self):
        src = _read("apps/agentic/tools.py")
        self.assertIn("create_doc(", src)                        # prompt saved as a document
        self.assertIn('linked_entity_type="job"', src)
        self.assertIn('linked_entity_id="agentic"', src)
        for key in ('"prompt_doc_id"', '"tool_categories"', '"tier"'):
            self.assertIn(key, src)                              # job_config spec

    def test_handler_loads_prompt_and_is_category_based(self):
        src = _read("apps/agentic/agentic.py")
        self.assertIn("get_document_content", src)               # prompt from the d-* doc
        self.assertIn("request_tools", src)                      # request more on demand
        self.assertIn("after_round=_after_round", src)           # tools rebuilt on request
        self.assertIn("_awareness", src)                         # loaded-category awareness

    def test_handler_has_no_artificial_limits(self):
        # The prompt drives everything, incl. notifying people via the ORDINARY
        # tools — no mouthless refusal, no needs_attention machinery.
        src = _read("apps/agentic/agentic.py")
        self.assertNotIn("REFUSED", src)
        self.assertNotIn("_MESSAGING_TOOLS", src)
        self.assertNotIn("needs_attention", src)
        # it wires the real local tools (send_notification, send_message_to_user…)
        self.assertIn("LOCAL_TOOLS", src)
        self.assertIn("handle_local_tool", src)

    def test_no_needs_attention_anywhere(self):
        for f in ("apps/agentic/tools.py", "apps/agentic/routes.py",
                  "apps/schedules/ui/SchedulesApp.jsx"):
            self.assertNotIn("needs_attention", _read(f), f)
        # the voice-delivery skill is gone (delivery is the prompt's job now)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "apps/agentic/handlers.py")))

    def test_view_and_edit_tools_exist(self):
        src = _read("apps/agentic/tools.py")
        self.assertIn("def show_routine", src)
        self.assertIn("def update_routine", src)
        self.assertIn("get_document_content", src)
        self.assertIn("update_doc(", src)

    def test_update_schedule_persists_job_config(self):
        src = _read("apps/schedules/data.py")
        allowed = src.split("allowed = {", 1)[1].split("}", 1)[0]
        self.assertIn('"job_config"', allowed)
        self.assertIn('("recurrence_rule", "job_config")', src)

    def test_create_from_schedules_ui(self):
        r = _read("apps/agentic/routes.py")
        self.assertIn('@router.post("/routines")', r)
        self.assertIn('@router.get("/categories")', r)
        ui = _read("apps/schedules/ui/SchedulesApp.jsx")
        self.assertIn("New Routine", ui)
        self.assertIn("New Routine", ui)
        self.assertIn('/api/apps/agentic/routines', ui)

    def test_recurrence_picker_shared_by_both_forms(self):
        # the "Repeats + day-of-week/month/etc." picker is one shared component,
        # so the Task form has the same full recurrence UI as the Schedule form.
        ui = _read("apps/schedules/ui/SchedulesApp.jsx")
        self.assertIn("function RecurrenceFields", ui)
        self.assertEqual(ui.count("<RecurrenceFields"), 2)   # both forms use it
        self.assertIn('recurrence_rule: recur.rule', ui)     # the Task form sends the rule
        # backend threads the rule through
        self.assertIn("recurrence_rule", _read("apps/agentic/tools.py"))
        self.assertIn("recurrence_rule", _read("apps/agentic/routes.py"))

    def test_schedules_ui_surfaces_agentic_tasks(self):
        ui = _read("apps/schedules/ui/SchedulesApp.jsx")
        self.assertIn('linked_entity_id === "agentic"', ui)
        self.assertIn("View / edit prompt", ui)
        self.assertIn('onOpenApp?.("document"', ui)
        self.assertIn("assigned_to=created_by.strip()", _read("apps/agentic/tools.py"))


if __name__ == "__main__":
    unittest.main()
