"""Real Nix transitive corruption and cold-recovery contract, no model/services.

--mutation skip-verify removes this change's restore gate and must turn red.
All store writes are in two TemporaryDirectory stores, never the runner store.
"""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import nix_cache

EXPR = 'let dep = builtins.toFile "ci-cache-dependency" "CLEAN"; in builtins.toFile "ci-cache-root" dep'


def seed(closure, store):
    root = subprocess.run([closure.NIX, *closure.NIX_FEATURES, '--store', str(store),
                           'eval', '--raw', '--expr', EXPR], text=True,
                          capture_output=True, check=True, timeout=30).stdout.strip()
    return dict(schema=closure.SCHEMA, kind='nix_store', store_path=root,
                requisites=closure.path_info(root, store=store))


def isolated_bootstrap(args, closure, parent, store, manifest):
    source = args.src.resolve()
    meta = parent / 'order'; meta.mkdir()
    bootstrap = nix_cache.bootstrap_record(closure.NIX)
    identity = {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'GITHUB_RUN_ID': 'bootstrap-order',
                'RUNNER_ENVIRONMENT': 'github-hosted', 'CI_OUT': str(parent / 'out')}
    load = nix_cache.module
    with patch.dict(os.environ, identity):
        (meta / 'empty-store-owner').write_text(identity['GITHUB_RUN_ID'])
        metadata = dict(schema=nix_cache.SCHEMA, inputs=nix_cache.inputs(source),
                        platform=nix_cache.platform(), manifest=manifest, bootstrap=bootstrap,
                        fingerprint=closure.manifest_fingerprint(manifest), store_key=nix_cache.store_key(source))
        (meta / 'manifest.json').write_text(json.dumps(metadata))
        with patch.dict(os.environ, PATH=str(parent / 'empty-path')), \
                patch.object(closure, 'PROFILE_BIN', parent / 'missing-profile'), \
                patch.object(nix_cache, 'module', side_effect=lambda src, name: closure if name == 'nix_closure' else load(src, name)), \
                (patch.object(nix_cache, 'bootstrap_tools', lambda _nix: nullcontext())
                 if args.mutation == 'unbound-bootstrap' else nullcontext()):
            checked = nix_cache.check(source, meta, store=store)
    assert checked['state'] in {'hit', 'rejected-cold'}, checked
    assert store.exists() == (checked['state'] == 'hit'), checked
    return checked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', type=Path, required=True)
    parser.add_argument('--mutation', choices=['skip-verify', 'unbound-bootstrap'])
    parser.add_argument('--bootstrap-order', action='store_true')
    args = parser.parse_args()
    closure = nix_cache.module(args.src.resolve(), 'nix_closure')
    nix_cache.bind_nix(closure)
    with tempfile.TemporaryDirectory(prefix='nix-gha-contract-') as tmp:
        parent = Path(tmp)
        store = parent / 'restored'
        manifest = seed(closure, store)
        value = dict(manifest=manifest)
        nix_cache.verify(value, closure, store=store)
        if args.bootstrap_order:
            checked = isolated_bootstrap(args, closure, parent, store, manifest)
            return int(checked['state'] != 'hit')
        dependency = next(row['path'] for row in manifest['requisites'] if row['path'].endswith('-ci-cache-dependency'))
        physical = store / dependency.lstrip('/')
        physical.chmod(0o644)
        physical.write_text('DIRTY')
        # The root metadata/hash stays unchanged. Only the transitive bytes vary.
        assert closure.path_info(manifest['store_path'], store=store) == manifest['requisites']
        os.environ.setdefault('RUNNER_OS', 'Linux')
        os.environ.setdefault('RUNNER_ARCH', 'X64')
        os.environ.setdefault('GITHUB_RUN_ID', 'contract')
        os.environ['RUNNER_ENVIRONMENT'] = 'github-hosted'
        os.environ['CI_OUT'] = str(parent / 'out')
        meta = parent / 'meta'; meta.mkdir()
        (meta / 'empty-store-owner').write_text(os.environ['GITHUB_RUN_ID'])
        fingerprint = closure.manifest_fingerprint(manifest)
        metadata = dict(schema=nix_cache.SCHEMA, inputs=nix_cache.inputs(args.src.resolve()),
                        platform=nix_cache.platform(), manifest=manifest, bootstrap=nix_cache.bootstrap_record(closure.NIX),
                        fingerprint=fingerprint,
                        store_key=nix_cache.store_key(args.src.resolve()))
        (meta / 'manifest.json').write_text(json.dumps(metadata))
        original = nix_cache.verify
        if args.mutation:
            nix_cache.verify = lambda *a, **kw: None
        try:
            with patch.object(Path, 'home', side_effect=AssertionError('restored bootstrap must not consult HOME profiles')):
                restored = nix_cache.check(args.src.resolve(), meta, store=store)
        finally:
            nix_cache.verify = original
        if restored['state'] != 'rejected-cold' or store.exists():
            print(json.dumps(dict(successful=False, negative_control_reproduced=True,
                                  corrupt_dependency_accepted=True)))
            return 1
        assert list(parent.glob('restored-cache-rejected-*'))
        # The production gate quarantined the store. Original setup now sees
        # an empty location and reconstructs the same frozen input from cold.
        cold = seed(closure, store)
        assert cold == manifest
        with patch.object(Path, 'home', side_effect=AssertionError('restored bootstrap must not consult HOME profiles')):
            recovered = nix_cache.check(args.src.resolve(), meta, store=store)
        assert recovered['state'] == 'hit'
        print(json.dumps(dict(successful=True, corrupt_dependency_rejected=True,
                              cold_recovery_verified=True, requisites=len(manifest['requisites']))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
