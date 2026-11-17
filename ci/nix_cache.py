"""GHA cache policy/receipts; Nix owns manifests and content verification.

Only an empty, ephemeral hosted store can be restored. A rejected restored
store is quarantined so the existing target setup performs a real cold install.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

SCHEMA = 'testkit-gha-nix-cache-1'


def module(src, name):
    spec = importlib.util.spec_from_file_location(name, src / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inputs(src):
    return module(src, 'ci_nix').identity(src)


def emit(**values):
    path = os.environ.get('GITHUB_OUTPUT')
    if path:
        with open(path, 'a') as stream:
            for key, value in values.items():
                stream.write(f'{key}={value}\n')
    print(json.dumps(values, sort_keys=True))


def env(**values):
    path = os.environ.get('GITHUB_ENV')
    if path:
        with open(path, 'a') as stream:
            for key, value in values.items():
                stream.write(f'{key}={value}\n')


def platform():
    return os.environ['RUNNER_OS'] + '-' + os.environ['RUNNER_ARCH']


def store_key(src, fingerprint):
    return f'testkit-nix-store-v1-{platform()}-{inputs(src)["flake.lock"]}-{fingerprint}'


def identity(src, meta):
    meta.mkdir(parents=True, exist_ok=True)
    emit(index_key=f'testkit-nix-index-v1-{platform()}-{inputs(src)["flake.lock"]}-{digest(inputs(src))}')


def read(src, meta):
    value = json.loads((meta / 'manifest.json').read_text())
    closure = module(src, 'nix_closure')
    frozen = closure.validate(value['manifest'], frozen=True)
    fingerprint = closure.manifest_fingerprint(frozen)
    if (value['schema'] != SCHEMA or value['inputs'] != inputs(src)
            or value['platform'] != platform() or value['fingerprint'] != fingerprint
            or value['store_key'] != store_key(src, fingerprint)):
        raise ValueError('cached frozen manifest/inputs/key mismatch')
    return value, closure


def select(src, meta):
    # Never merge an archive into an existing store or operate on self-hosted Nix.
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or Path('/nix/var/nix/db/db.sqlite').exists():
        emit(store_key='', reason='existing or non-hosted store; normal target setup')
        return
    try:
        value, _ = read(src, meta)
    except (OSError, ValueError, KeyError, TypeError) as error:
        emit(store_key='', reason=f'index miss/rejected: {error}')
        return
    subprocess.run(['sudo', 'mkdir', '-p', '/nix'], check=True)
    subprocess.run(['sudo', 'chown', str(os.getuid()), '/nix'], check=True)
    (meta / 'empty-store-owner').write_text(os.environ['GITHUB_RUN_ID'])
    emit(store_key=value['store_key'])


def bind_nix(closure):
    candidates = [Path('/nix/var/nix/profiles/default/bin/nix'), Path.home() / '.nix-profile/bin/nix']
    candidates += list(Path('/nix/var/nix/profiles/per-user').glob('*/profile/bin/nix'))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            closure.NIX = str(candidate)
            closure.NIX_STORE = str(candidate.with_name('nix-store'))
            return candidate
    raise ValueError('restored store has no bootstrap Nix')


def verify(value, closure, *, store=None):
    # This must stay on the restore path. Metadata equality alone misses changed
    # bytes in a transitive dependency whose root and DB still look unchanged.
    return closure.verify(value['manifest'], store=store)


def check(src, meta, *, store=None):
    started = time.monotonic()
    state = 'hit'
    try:
        value, closure = read(src, meta)
        nix = bind_nix(closure)
        verify(value, closure, store=store)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # The marker predates restore and is outside /nix. Move only the empty
        # hosted store this action owns; retain its bytes for diagnostics.
        marker = meta / 'empty-store-owner'
        if (os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
                or not marker.is_file() or marker.read_text() != os.environ['GITHUB_RUN_ID']):
            raise RuntimeError('cannot quarantine a store this run does not own') from error
        source = Path('/nix') if store is None else Path(store)
        quarantine = source.with_name(source.name + '-cache-rejected-' + uuid.uuid4().hex)
        if store is None:
            subprocess.run(['sudo', 'mv', str(source), str(quarantine)], check=True)
        else:
            # Internal integration seam only; the CLI never accepts this option.
            source.rename(quarantine)
        state = 'rejected-cold'
        print(f'::warning::Nix cache rejected; cold target setup follows: {error}; quarantine={quarantine}')
    else:
        env(TESTKIT_NIX_BIN=str(nix))
    env(TESTKIT_NIX_CACHE_STATE=state)
    record = dict(state=state, verify_seconds=time.monotonic() - started)
    output = Path(os.environ['CI_OUT']); output.mkdir(parents=True, exist_ok=True)
    (output / 'nix-cache-restore.json').write_text(json.dumps(record, indent=2) + '\n')
    emit(**record)
    return record


def freeze(src, meta):
    # Defence in depth: the workflow ref AND the tested commit must be default
    # main. Dispatching a PR SHA from ci-worker main must never enable writes.
    if (os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') == 'pull_request'
            or os.environ.get('CI_JOB') != 'static'):
        emit(save='false', reason='reader only')
        return
    if os.environ.get('TESTKIT_NIX_CACHE_STATE') == 'hit':
        emit(save='false', reason='verified shared cache already exists')
        return
    main = os.environ['CI_REF_SHA']
    # static has fetch-depth: 0. Trust the default-branch history fetched by
    # checkout, so a later merge cannot invalidate a pinned main-SHA benchmark.
    ancestry = subprocess.run(['git', 'merge-base', '--is-ancestor', main,
                              'refs/remotes/origin/main'], cwd=src,
                             text=True, capture_output=True, timeout=30)
    if ancestry.returncode != 0:
        emit(save='false', reason='tested SHA is not target main history')
        return
    closure = module(src, 'nix_closure')
    nix = bind_nix(closure)
    profile = meta / 'environment'
    subprocess.run([str(nix), *closure.NIX_FEATURES, 'print-dev-env', '--no-update-lock-file',
                    '--profile', str(profile), '--json', str(src)], check=True,
                   stdout=subprocess.DEVNULL, timeout=180)
    manifest = closure.freeze_record(dict(kind='nix_store', store_path=str(profile.resolve())))
    fingerprint = closure.manifest_fingerprint(manifest)
    key = store_key(src, fingerprint)
    value = dict(schema=SCHEMA, platform=platform(), inputs=inputs(src), manifest=manifest,
                 fingerprint=fingerprint, store_key=key, source_sha=main,
                 closure_nar_bytes=sum(row['nar_size'] for row in manifest['requisites']))
    (meta / 'manifest.json').write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    # The /nix archive includes the bootstrap and evaluation sources as well.
    size = int(subprocess.run(['du', '-sb', '/nix'], text=True, capture_output=True,
                              check=True, timeout=60).stdout.split()[0])
    print(json.dumps(dict(store_bytes=size, closure_nar_bytes=value['closure_nar_bytes'],
                          requisites=len(manifest['requisites']))))
    # Leave headroom below the repository's 10 GiB quota. Never evict other CI
    # caches or save one copy per shard. GitHub owns LRU eviction of older keys.
    if size > 8 * 1024**3:
        emit(save='false', reason='store exceeds 8 GiB cache budget', store_bytes=size)
        return
    emit(save='true', store_key=key, store_bytes=size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['identity', 'select', 'check', 'freeze'])
    parser.add_argument('--src', type=Path, required=True)
    parser.add_argument('--meta', type=Path, required=True)
    args = parser.parse_args()
    globals()[args.command](args.src.resolve(), args.meta.resolve())


if __name__ == '__main__':
    main()
