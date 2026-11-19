"""Collect the checked-out PR's change set and verify prior Rust receipts."""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import Request, urlopen
import zipfile

from verification import skip_receipt

SHA = re.compile(r'[0-9a-f]{40}')
FINGERPRINT = re.compile(r'[0-9a-f]{64}')
MAX_MARKER_BYTES = 4096
MAX_ARCHIVE_BYTES = 65536


def requested_base(event, source, group, ref, base):
    # The scheduled poll can discover a genuine PR. A test-unit schedule,
    # a manual request, or a branch head must execute the entire suite.
    if (event == 'repository_dispatch' and source == 'poll'
            and re.fullmatch(r'pr-[1-9][0-9]*', group)
            and SHA.fullmatch(ref) and SHA.fullmatch(base)):
        return base
    return None


def changed_paths(src, base, head):
    if not SHA.fullmatch(base or ''):
        return None, None
    try:
        git = ['git', '-C', str(src)]
        subprocess.run(git + ['merge-base', base, head], capture_output=True, check=True, timeout=20)
        paths = subprocess.check_output(git + ['diff', '--name-only', '-z', '--no-renames', f'{base}...{head}', '--'],
                                        stderr=subprocess.PIPE, timeout=20)
        return base, sorted({part.decode() for part in paths.split(b'\0') if part})
    except (subprocess.SubprocessError, UnicodeError) as error:
        print(f'::warning::affected paths unavailable, running the full plan: {error}')
        return None, None


def fingerprint(src):
    """Evaluate the target's RUSTF identity using its pinned Nix CLI."""
    with tempfile.TemporaryDirectory(prefix='ciw-fingerprint-') as work:
        env = {name: value for name, value in os.environ.items()
               if name not in {'GITHUB_OUTPUT', 'GITHUB_ENV', 'GITHUB_PATH', 'GITHUB_STEP_SUMMARY',
                               'GIE_GIT_TOKEN', 'CI_ARTIFACT_TOKEN'}}
        env.update(TEST_UNIT_SETUP='nix', CI_OUT=work, TESTKIT_NIX_STATE=f'{work}/nix')
        subprocess.run(['bash', 'nix/ci.sh', 'setup'], cwd=src, env=env, check=True, timeout=100)
        output = Path(work) / 'key'
        subprocess.run(
            ['bash', 'nix/ci.sh', 'run', 'python', '-B',
             'e2e/cases/nix_cpu_mocker_rust_shared_store/ci.py', 'key',
             '--shared', f'{work}/shared', '--output', str(output)],
            cwd=src, env=env, check=True, timeout=75)
        value = json.loads((output / 'verification.json').read_text())['verification']
        if not FINGERPRINT.fullmatch(value):
            raise ValueError('target returned an invalid verification fingerprint')
        return value


def github(path, *, size=MAX_ARCHIVE_BYTES):
    repository = os.environ['GITHUB_REPOSITORY']
    url = f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{repository}/{path}"
    # GitHub redirects artifact downloads to a signed object URL. Do not send
    # the Actions token to that host.
    request = Request(url, headers={'Accept': 'application/vnd.github+json'})
    request.add_unredirected_header('Authorization', 'Bearer ' + os.environ['CI_ARTIFACT_TOKEN'])
    with urlopen(request, timeout=10) as response:
        content = response.read(size + 1)
    if len(content) > size:
        raise ValueError('verification artifact or response exceeds its size limit')
    return content


def find_markers(value, jobs, head, request=github):
    indexed = f'verification-markers-{value}'
    wanted = {job['verification']['suite']: job['id'] for job in jobs}
    matches = {}
    # #15 published the same receipt schema under a fixed artifact name.
    # Checking it after the indexed name keeps the rollout backward compatible.
    for name in (indexed, 'verification-markers'):
        entries = json.loads(request(f'actions/artifacts?name={name}&per_page=20', size=200000))['artifacts']
        for artifact in entries[:4]:
            origin = artifact.get('workflow_run') or {}
            if (artifact.get('expired') or artifact.get('name') != name
                    or origin.get('head_branch') != os.environ.get('GITHUB_REF_NAME', 'main')
                    or not origin.get('id') or artifact.get('size_in_bytes', 0) > MAX_ARCHIVE_BYTES):
                continue
            run_id = origin['id']
            if run_id == int(os.environ.get('GITHUB_RUN_ID', '0')):
                continue
            run = json.loads(request(f'actions/runs/{run_id}'))
            if (run.get('conclusion') != 'success' or run.get('path', '').split('@', 1)[0]
                    != '.github/workflows/run-test-unit.yml'):
                continue
            with zipfile.ZipFile(io.BytesIO(request(f"actions/artifacts/{artifact['id']}/zip"))) as archive:
                for suite, job in wanted.items():
                    if job in matches:
                        continue
                    try:
                        entry = archive.getinfo(f'{suite}/result.json')
                        if entry.file_size > MAX_MARKER_BYTES:
                            continue
                        marker = json.loads(archive.read(entry))
                        if not isinstance(marker, dict) or marker.get('run_id') != run_id:
                            continue
                        receipt = skip_receipt(marker, value, suite, head)
                        if receipt:
                            matches[job] = receipt
                    except (KeyError, ValueError, OSError):
                        continue
            if len(matches) == len(wanted):
                return matches
    return matches


def prune(src, jobs, head, affected, verify_always, evaluate=fingerprint, lookup=find_markers):
    mandatory = set(affected.get('mandatory', ()))
    candidates = [job for job in jobs if job.get('verification') and job['id'] not in mandatory]
    if not candidates or verify_always or affected.get('full'):
        return jobs, None, {}
    try:
        value = evaluate(src)
        verified = lookup(value, candidates, head)
    except (KeyError, OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f'::warning::verification lookup unavailable, executing selected jobs: {error}')
        return jobs, None, {}
    verified = {job['id']: verified[job['id']] for job in candidates if job['id'] in verified}
    return [job for job in jobs if job['id'] not in verified], value, verified
