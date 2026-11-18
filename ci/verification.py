"""Read and publish small, exact-fingerprint CI pass markers."""
import argparse
import json
import os
from pathlib import Path
import re


def cache_key(verification, fingerprint):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', verification['namespace']):
        raise ValueError('invalid verification cache namespace')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', verification['suite']):
        raise ValueError('invalid verification suite')
    if not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise ValueError('missing or invalid shared verification fingerprint')
    return f"{verification['namespace']}-{verification['suite']}-{fingerprint}"


def marker_for_result(result, fingerprint, suite, head, run_id, run_attempt):
    if (result.get('successful') is not True or result.get('skipped') is True
            or result.get('testkit_head', result.get('head')) != head
            or result.get('suite', suite) != suite):
        raise ValueError('verification marker requires a successful, executed result for this revision')
    return dict(successful=True, head=head, fingerprint=fingerprint, suite=suite,
                run_id=run_id, run_attempt=run_attempt)


def skip_receipt(marker, fingerprint, suite, head):
    if (not isinstance(marker, dict) or marker.get('successful') is not True
            or marker.get('fingerprint') != fingerprint or marker.get('suite') != suite
            or not re.fullmatch(r'[0-9a-f]{40}', str(marker.get('head', '')))
            or type(marker.get('run_id')) is not int or marker['run_id'] < 1
            or type(marker.get('run_attempt')) is not int or marker['run_attempt'] < 1):
        return None
    return dict(successful=True, head=head, skipped=True, reason='verified-fingerprint',
                fingerprint=fingerprint, suite=suite, verified_head=marker['head'],
                verified_run_id=marker['run_id'], verified_run_attempt=marker['run_attempt'])


def output(name, value):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write(f'{name}={value}\n')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


def read_marker(path):
    try:
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 4096:
            return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('key', 'skip', 'publish'))
    args = parser.parse_args()
    fingerprint = os.environ['VERIFICATION_FINGERPRINT']
    if args.operation in ('key', 'skip'):
        verification = json.loads(os.environ['VERIFICATION_PLAN'])
        key = cache_key(verification, fingerprint)
        if args.operation == 'key':
            output('key', key)
            return
        marker = read_marker(Path(os.environ['VERIFICATION_MARKER']))
        result = skip_receipt(marker, fingerprint, verification['suite'], os.environ['CI_REF_SHA'])
        if result is not None:
            write(Path(os.environ['CI_OUT']) / os.environ['CI_JOB'] / 'result.json', result)
            print(json.dumps(result, sort_keys=True))
            output('skip', 'true')
        return

    jobs = json.loads(os.environ['JOBS'])
    ci_in = Path(os.environ['CI_IN'])
    marker_root = Path(os.environ['VERIFICATION_ROOT'])
    head = os.environ['CI_REF_SHA']
    run_id = int(os.environ['GITHUB_RUN_ID'])
    run_attempt = int(os.environ['GITHUB_RUN_ATTEMPT'])
    markers = []
    for job in jobs:
        verification = job.get('verification')
        if not verification:
            continue
        job_id = job['id']
        suite = verification['suite']
        result = json.loads((ci_in / f'job-{job_id}' / job_id / 'result.json').read_text())
        if result.get('skipped') is True:
            continue
        key = cache_key(verification, fingerprint)
        marker = marker_for_result(result, fingerprint, suite, head, run_id, run_attempt)
        write(marker_root / suite / 'result.json', marker)
        markers.append(dict(suite=suite, key=key))
    output('markers', json.dumps(markers, separators=(',', ':')))


if __name__ == '__main__':
    main()
