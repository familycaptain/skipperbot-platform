"""#109 — autonomous scheduled tasks. Contract checks for the agentic app:
a task = a schedule (job_config spec) + a d-* prompt doc + the agentic job type;
the handler is mouthless + category-based; needs_attention results reach the
voice. (End-to-end run verified live on the test box.)

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
        # prompt saved as a document
        self.assertIn("create_doc(", src)
        # schedule linked to the agentic job type
        self.assertIn('linked_entity_type="job"', src)
        self.assertIn('linked_entity_id="agentic"', src)
        # job_config carries the full spec
        for key in ('"prompt_doc_id"', '"tool_categories"', '"needs_attention"', '"tier"'):
            self.assertIn(key, src)

    def test_handler_loads_prompt_and_is_category_based(self):
        src = _read("apps/agentic/agentic.py")
        self.assertIn("get_document_content", src)          # prompt from the d-* doc
        self.assertIn("request_tools", src)                 # request more on demand
        self.assertIn("after_round=_after_round", src)      # tools rebuilt on request
        self.assertIn("_awareness", src)                    # loaded-category awareness

    def test_handler_is_mouthless(self):
        src = _read("apps/agentic/agentic.py")
        self.assertIn("_MESSAGING_TOOLS", src)
        self.assertIn("REFUSED", src)
        for t in ("send_message", "send_dm", "send_notification"):
            self.assertIn(t, src)  # named in the refusal set

    def test_needs_attention_raises_event_for_voice(self):
        src = _read("apps/agentic/agentic.py")
        self.assertIn("needs_attention", src)
        self.assertIn('domain="agentic"', src)
        self.assertIn("needs_attention=True", src)

    def test_voice_skill_registered(self):
        h = _read("apps/agentic/handlers.py")
        self.assertIn('register_skill("agentic"', h)
        self.assertIn("send_message", h)   # delivers in Skipper's voice


if __name__ == "__main__":
    unittest.main()
