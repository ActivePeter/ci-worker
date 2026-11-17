"""Guard the entry plan sanity limit independently of runner capacity."""
import unittest

from plan import normalize


class PlanJobLimit(unittest.TestCase):
    def test_thirteen_and_sixteen_jobs_are_accepted_but_seventeen_are_rejected(self):
        for count in (13, 16):
            with self.subTest(count=count):
                plan = {"version": 1, "jobs": [{"id": f"job-{i}"} for i in range(count)]}
                jobs, report = normalize(plan)
                self.assertEqual([job["id"] for job in jobs], [job["id"] for job in plan["jobs"]])
                self.assertFalse(report)
        with self.assertRaisesRegex(ValueError, r"^plan must declare 1\.\.16 jobs$"):
            normalize({"version": 1, "jobs": [{"id": f"job-{i}"} for i in range(17)]})


if __name__ == "__main__":
    unittest.main()
