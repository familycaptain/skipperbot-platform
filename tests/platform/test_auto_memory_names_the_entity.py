"""An auto-memory names the thing that changed (platform.memory.auto-memory-names-the-entity).

On the operator's install a run of status changes produced fifty memories like
"[updated] task t-30ec504d: Status: not_started → cancelled" — unrecallable, because nobody asks
about t-30ec504d; they ask about the garage. log_entity_change now looks the name up through the
entity registry and puts it beside the id.

Run: python3 -m unittest tests.platform.test_auto_memory_names_the_entity
"""
import sys
import types
import unittest
from unittest import mock


class AutoMemoryNamesTheEntity(unittest.TestCase):
    def _log(self, *, row, summary, entity_id="t-30ec504d", raise_lookup=False):
        saved = []

        def get_entity(prefix, eid):
            if raise_lookup:
                raise KeyError(prefix)
            return row

        stubs = {
            "config": types.SimpleNamespace(logger=mock.Mock()),
            "memory_store": types.SimpleNamespace(save_memory=lambda **kw: saved.append(kw)),
            "app_platform": types.ModuleType("app_platform"),
            "app_platform.entities": types.SimpleNamespace(get_entity=get_entity),
            "data_layer": types.ModuleType("data_layer"),
            "data_layer.skipper_state": types.SimpleNamespace(create_state=lambda **kw: None),
        }
        with mock.patch.dict(sys.modules, stubs):
            sys.modules.pop("auto_memory", None)
            import auto_memory
            auto_memory.log_entity_change("updated", entity_id, "task", summary, by="rodney")
            sys.modules.pop("auto_memory", None)
        self.assertEqual(len(saved), 1)
        return saved[0]

    def test_the_name_goes_beside_the_id(self):
        m = self._log(row={"name": "Clean the gutters"},
                      summary="Status: not_started → cancelled")
        self.assertEqual(m["content"],
                         "[updated] task 'Clean the gutters' (t-30ec504d): "
                         "Status: not_started → cancelled")
        self.assertEqual(m["about"], "t-30ec504d")       # recall by entity still works

    def test_a_summary_that_already_names_it_is_not_doubled(self):
        m = self._log(row={"name": "Clean the gutters"}, summary="Clean the gutters deleted")
        self.assertEqual(m["content"], "[updated] task t-30ec504d: Clean the gutters deleted")

    def test_no_name_falls_back_to_the_old_shape(self):
        for kw in ({"row": None}, {"row": {"name": ""}}, {"row": None, "raise_lookup": True}):
            with self.subTest(**{k: str(v) for k, v in kw.items()}):
                m = self._log(summary="Status: done", **kw)
                self.assertEqual(m["content"], "[updated] task t-30ec504d: Status: done")


if __name__ == "__main__":
    unittest.main()
