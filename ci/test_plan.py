"""Guard the entry plan sanity limit independently of runner capacity."""
import unittest

from plan import normalize, normalize_shared


class PlanJobLimit(unittest.TestCase):
    def test_thirteen_sixteen_and_thirty_two_jobs_are_accepted_but_thirty_three_are_rejected(self):
        for count in (13, 16, 32):
            with self.subTest(count=count):
                plan = {"version": 1, "jobs": [{"id": f"job-{i}"} for i in range(count)]}
                jobs, report = normalize(plan)
                self.assertEqual([job["id"] for job in jobs], [job["id"] for job in plan["jobs"]])
                self.assertFalse(report)
        with self.assertRaisesRegex(ValueError, r"^plan must declare 1\.\.32 jobs$"):
            normalize({"version": 1, "jobs": [{"id": f"job-{i}"} for i in range(33)]})


class SharedPreparation(unittest.TestCase):
    def test_legacy_plan_has_no_preparation_or_consumers(self):
        plan = {"version": 1, "jobs": [{"id": "static"}]}
        self.assertIsNone(normalize_shared(plan))
        self.assertFalse(normalize(plan)[0][0]["shared"])

    def test_shared_stage_is_single_and_precedes_sixteen_consumers(self):
        plan = {"version": 1, "shared": {"id": "build-inputs", "timeout": 120, "fetch_depth": 0},
                "jobs": [{"id": f"test-{i}", "shared": True} for i in range(16)]}
        jobs, _ = normalize(plan)
        self.assertEqual(len(jobs), 16)
        self.assertTrue(all(job["shared"] for job in jobs))
        self.assertEqual(normalize_shared(plan), {"id": "build-inputs", "timeout": 60, "fetch_depth": 0})

    def test_consumers_cannot_request_a_missing_snapshot(self):
        with self.assertRaisesRegex(ValueError, "shared consumers require"):
            normalize({"version": 1, "jobs": [{"id": "test", "shared": True}]})

    def test_shared_id_cannot_duplicate_matrix_or_reserved_ids(self):
        for ident in ("test", "report", "bad/id"):
            with self.subTest(ident=ident), self.assertRaises(ValueError):
                normalize_shared({"version": 1, "shared": {"id": ident}, "jobs": [{"id": "test"}]})

    def test_shared_spec_rejects_unknown_or_non_object_configuration(self):
        for record in (False, [], {}, {"id": "inputs", "run": "echo unsupported"}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                normalize_shared({"version": 1, "shared": record, "jobs": [{"id": "test"}]})


if __name__ == "__main__":
    unittest.main()
