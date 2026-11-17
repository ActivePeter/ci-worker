"""Check the dag-panel gate keeps all existing checks and optional UI1 coverage."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import plan

ENTRY = Path(__file__).parent / 'defaults' / 'dag-panel.sh'


class DagPanelPlanTests(unittest.TestCase):
    def entry_plan(self, ui1):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'collab').mkdir()
            (root / 'collab/.nvmrc').write_text('20.20.2\n')
            (root / 'web').mkdir()
            (root / 'web/package.json').write_text('{"packageManager":"pnpm@10.15.1"}')
            if ui1:
                (root / 'testflows').mkdir()
                (root / 'testflows/machine-range-preview.cjs').touch()
            return json.loads(subprocess.check_output(['bash', str(ENTRY.resolve()), 'plan'], cwd=root))

    def test_old_heads_keep_all_six_checks(self):
        jobs, report = plan.normalize(self.entry_plan(False))
        self.assertEqual([j['id'] for j in jobs],
                         ['lint', 'unit', 'smoke', 'regression', 'performance', 'collector'])
        self.assertFalse(report)
        self.assertTrue(all(j['go'] and j['python'] == '3.12' for j in jobs))
        self.assertTrue(all(j['node'] == '20.20.2' and j['pnpm'] == '10.15.1' for j in jobs))
        self.assertEqual(jobs[0]['fetch_depth'], 0)

    def test_ui1_heads_add_browser_check(self):
        jobs, _ = plan.normalize(self.entry_plan(True))
        self.assertEqual(len(jobs), 7)
        self.assertEqual(jobs[-1]['id'], 'machine-ui1')

    def test_existing_repos_need_no_go_or_node(self):
        jobs, _ = plan.normalize({'version': 1, 'jobs': [{'id': 'existing', 'rust_cache': True}]})
        self.assertTrue(jobs[0]['rust_cache'])
        self.assertFalse(jobs[0]['go'])
        self.assertEqual(jobs[0]['node'], '')
        self.assertEqual(jobs[0]['pnpm'], '')

    def test_unknown_job_cannot_report_success(self):
        result = subprocess.run(['bash', str(ENTRY.resolve()), 'run', 'unknown'], capture_output=True)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
