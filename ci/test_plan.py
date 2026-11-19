"""Guard the entry plan sanity limit independently of runner capacity."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import plan as worker_plan
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


class FullRequest(unittest.TestCase):
    def test_main_and_scheduled_requests_keep_all_33_jobs_even_with_a_pr_base(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Fixture', '-c',
                            'user.email=ci@example.invalid', 'commit', '--allow-empty', '-qm', 'initial'],
                           check=True)
            head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            entry = root / worker_plan.TARGET_ENTRY
            entry.parent.mkdir(parents=True)
            entry.touch()
            suite = dict(id='rust-job', shared=True,
                         verification=dict(namespace='rust-verified-v1', suite='cache'))
            out = root / 'output'

            def target_plan(_command, *, env, **_kwargs):
                changed = json.loads(Path(env['CI_AFFECTED_CHANGES']).read_text())
                jobs = [suite] + [dict(id=f'case-{i}') for i in range(29)]
                return json.dumps(dict(version=1, jobs=jobs if changed is None else [suite],
                                       report=True, shared=dict(id='shared'),
                                       affected=dict(changed=changed)))

            subprocess_output = subprocess.check_output

            def local_output(cmd, **kwargs):
                if cmd[0] == 'bash':
                    return target_plan(cmd, **kwargs)
                return subprocess_output(cmd, **kwargs)

            scenarios = (
                ('push', 'poll', 'pr-42', head),
                ('repository_dispatch', 'poll', 'branch-main', head),
                ('repository_dispatch', 'poll', 'pr-42', 'refs/heads/main'),
                ('schedule', 'poll', 'pr-42', head),
                ('repository_dispatch', 'schedule', 'pr-42', head),
                ('workflow_dispatch', 'poll', 'pr-42', head),
            )
            for event, source, group, ref in scenarios:
                with self.subTest(event=event, source=source, group=group, ref=ref):
                    out.write_text('')
                    env = dict(SRC=str(root), CIW=str(root), REPO='goodputai/test', CONTEXT='local',
                               GITHUB_OUTPUT=str(out), GITHUB_EVENT_NAME=event, CI_REQUEST_SOURCE=source,
                               CI_REQUEST_GROUP=group, CI_REQUEST_REF=ref, CI_AFFECTED_BASE=head)
                    with (patch.dict(os.environ, env), patch.object(worker_plan.status, 'post'),
                          patch.object(worker_plan.status, 'run_url', return_value='local'),
                          patch.object(worker_plan.subprocess, 'check_output', side_effect=local_output),
                          patch.object(worker_plan.affected, 'fingerprint') as fingerprint,
                          patch.object(worker_plan.affected, 'find_markers') as markers):
                        worker_plan.main()
                    outputs = dict(line.split('=', 1) for line in out.read_text().splitlines())
                    jobs = json.loads(outputs['jobs'])
                    self.assertEqual(outputs['full_run'], 'true')
                    self.assertEqual(outputs['affected_base'], '')
                    self.assertEqual(len(jobs) + bool(outputs['shared']) + 2, 33)
                    self.assertIn('rust-job', {job['id'] for job in jobs})
                    fingerprint.assert_not_called()
                    markers.assert_not_called()


if __name__ == "__main__":
    unittest.main()
