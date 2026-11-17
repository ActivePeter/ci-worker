"""Boundary coverage for the public worker plan job limit."""
import unittest

from plan import normalize


class PlanJobLimit(unittest.TestCase):
    def accepted(self, count):
        declared = [dict(id=f'job-{index}') for index in range(count)]
        jobs, report = normalize(dict(version=1, jobs=declared, report=True))
        self.assertEqual([job['id'] for job in jobs], [job['id'] for job in declared])
        self.assertTrue(report)

    def test_thirteen_jobs_are_accepted(self):
        self.accepted(13)

    def test_sixteen_jobs_are_accepted(self):
        self.accepted(16)

    def test_seventeen_jobs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, r'plan must declare 1\.\.16 jobs'):
            normalize(dict(version=1, jobs=[dict(id=f'job-{index}') for index in range(17)]))


if __name__ == '__main__':
    unittest.main()
