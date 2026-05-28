import unittest
from unittest.mock import patch

from apps.medical import data, tools


class MedicalLabToolsTests(unittest.TestCase):
    def test_get_lab_results_by_date_uses_exact_date_query(self):
        member = {"id": "mmbr-alice", "name": "Alice"}
        lab_rows = [
            {
                "id": "mlbr-calcium",
                "member_id": "mmbr-alice",
                "member_name": "Alice",
                "event_id": "mevt-lab",
                "lab_test_id": "mlbt-calcium",
                "test_name": "Calcium",
                "unit": "mg/dL",
                "result_date": "2026-05-05",
                "value": 8.6,
                "notes": "",
            },
            {
                "id": "mlbr-pth",
                "member_id": "mmbr-alice",
                "member_name": "Alice",
                "event_id": "mevt-lab",
                "lab_test_id": "mlbt-pth",
                "test_name": "PTH",
                "unit": "pg/mL",
                "result_date": "2026-05-05",
                "value": 514.0,
                "notes": "",
            },
        ]

        calls = []

        def fake_get_lab_results(**kwargs):
            calls.append(kwargs)
            return lab_rows

        with patch.object(data, "get_member_by_name", lambda name: member), \
             patch.object(data, "get_lab_results", fake_get_lab_results):
            result = tools.get_lab_results_by_date("2026-05-05", "Alice")

        self.assertEqual(result["count"], 2)
        self.assertEqual(calls, [{
            "member_id": "mmbr-alice",
            "event_id": "",
            "result_date": "2026-05-05",
            "include_details": True,
        }])
        self.assertEqual(
            [item["test_name"] for item in result["summary"]],
            ["Calcium", "PTH"],
        )

    def test_get_lab_results_can_filter_exact_date_with_details(self):
        captured = {}

        def fake_fetch_all(schema, sql, params=()):
            captured["schema"] = schema
            captured["sql"] = sql
            captured["params"] = params
            return []

        with patch.object(data, "fetch_all_in_schema", fake_fetch_all):
            result = data.get_lab_results(
                member_id="mmbr-alice",
                result_date="2026-05-05",
                include_details=True,
            )

        self.assertEqual(result, [])
        self.assertEqual(captured["schema"], data.SCHEMA)
        self.assertIn("JOIN medical_lab_tests", captured["sql"])
        self.assertIn("r.result_date = %s", captured["sql"])
        self.assertEqual(captured["params"], ("mmbr-alice", "2026-05-05"))


if __name__ == "__main__":
    unittest.main()
