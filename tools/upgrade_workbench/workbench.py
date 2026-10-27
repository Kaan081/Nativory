#!/usr/bin/env python3
"""RN Upgrade Workbench alpha: limited preflight + controlled fix evidence.

Python 3.10+. preflight is strictly read-only. verify executes commands supplied
by the developer in two explicitly selected workspaces; it MUST NOT be used
with untrusted manifests, on a production checkout, or on the app under study.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from expo_kotlin_preflight import evaluate

SCHEMA = "rn-upgrade-workbench-alpha-0.1"
MAX_LOG_READ = 8 * 1024 * 1024
MAX_SOURCE_SIZE = 3 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_inside(root: Path, relative: str, *, require_dir: bool = False) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("INVALID_RELATIVE_PATH")
    if any(part in ("..", ".") for part in Path(relative).parts):
        raise ValueError("PATH_TRAVERSAL_FORBIDDEN")
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("SYMLINK_IN_WORKSPACE_PATH")
    target = path.resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("WORKSPACE_ESCAPE") from exc
    if require_dir and not target.is_dir():
        raise ValueError("MISSING_WORKSPACE_DIRECTORY")
    return target


def load_manifest(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > 100_000:
        raise ValueError("MANIFEST_TOO_LARGE")
    doc = json.loads(raw.decode('utf-8'))
    if not isinstance(doc, dict) or doc.get('schema_version') != 'rn-upgrade-case-0.1':
        raise ValueError("UNSUPPORTED_CASE_SCHEMA")
    if not isinstance(doc.get('case_id'), str) or not doc['case_id'].strip():
        raise ValueError("CASE_ID_REQUIRED")
    if doc.get('scope') not in ('isolated_compiler_compile', 'scoped_gradle_task', 'user_defined_command'):
        raise ValueError("INVALID_SCOPE")
    for key in ('failure_marker', 'after_artifact_marker'):
        if not isinstance(doc.get(key), str) or not 5 <= len(doc[key]) <= 300:
            raise ValueError(f"INVALID_{key.upper()}")
    runs = doc.get('runs')
    if not isinstance(runs, dict) or set(runs) != {'before', 'after'}:
        raise ValueError("REQUIRE_BEFORE_AFTER_RUNS")
    for arm in runs.values():
        if not isinstance(arm, dict) or not isinstance(arm.get('cwd'), str):
            raise ValueError("INVALID_CWD")
        argv = arm.get('argv')
        if not isinstance(argv, list) or not (1 <= len(argv) <= 50) or any(
            not isinstance(x, str) or not x or len(x) > 500 for x in argv
        ):
            raise ValueError("INVALID_COMMAND_ARGV")
        sources = arm.get('sources', [])
        if not isinstance(sources, list) or len(sources) > 30 or any(not isinstance(x, str) for x in sources):
            raise ValueError("INVALID_SOURCES")
    return doc


def capture_sources(cwd: Path, sources: list[str]) -> list[dict]:
    result = []
    for rel in sources:
        p = require_inside(cwd, rel)
        if not p.is_file() or p.stat().st_size > MAX_SOURCE_SIZE:
            result.append({'path': rel, 'status': 'NOT_READ'})
        else:
            result.append({'path': rel, 'status': 'HASHED', 'sha256': digest(p.read_bytes())})
    return result


def run_arm(arm: dict, workspace_root: Path, out: Path, role: str, timeout: int) -> dict:
    cwd = require_inside(workspace_root, arm['cwd'], require_dir=True)
    sources_before = capture_sources(cwd, arm.get('sources', []))
    log = out / f'{role}.log'
    start = time.monotonic()
    exit_code = None
    execution_error = None
    try:
        with log.open('wb') as f:
            completed = subprocess.run(
                arm['argv'], cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                shell=False, timeout=timeout, check=False,
            )
            exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        execution_error = 'TIMEOUT'
    except OSError as e:
        execution_error = 'PROCESS_LAUNCH_FAILED:' + type(e).__name__
    elapsed = round(time.monotonic() - start, 2)
    sources_after = capture_sources(cwd, arm.get('sources', []))
    source_drift = sources_before != sources_after
    raw = log.read_bytes() if log.exists() else b''
    log_oversize = len(raw) > MAX_LOG_READ
    parsed = raw[:MAX_LOG_READ].decode('utf-8', errors='replace')
    return {
        'role': role,
        'argv': arm['argv'],
        'cwd': arm['cwd'],
        'exit_code': exit_code,
        'execution_error': execution_error,
        'elapsed_seconds': elapsed,
        'log_file': log.name,
        'log_sha256': digest(raw),
        'log_bytes': len(raw),
        'log_oversize': log_oversize,
        'log_text': parsed,
        'sources_before': sources_before,
        'sources_after': sources_after,
        'source_drift': source_drift,
    }


def classify(before: dict, after: dict, failure_marker: str, artifact_marker: str) -> tuple[str, list[str]]:
    observations = []
    if any(x['execution_error'] for x in (before, after)):
        return 'UNKNOWN_EXECUTION_ERROR', [x['execution_error'] for x in (before, after) if x['execution_error']]
    if any(x['log_oversize'] for x in (before, after)):
        return 'UNKNOWN_LOG_OVERSIZE', ['LOG_LIMIT_REACHED']
    if any(x['source_drift'] for x in (before, after)):
        return 'UNKNOWN_SOURCE_DRIFT', ['DECLARED_SOURCE_CHANGED_DURING_COMMAND']
    if before['exit_code'] == 0:
        return 'UNKNOWN_BEFORE_FAILURE_NOT_REPRODUCED', ['BEFORE_EXIT_ZERO']
    if failure_marker not in before['log_text']:
        return 'UNKNOWN_BEFORE_DIFFERENT_FAILURE', ['BEFORE_EXPECTED_MARKER_ABSENT']
    observations.append('BEFORE_FAILED_WITH_EXPECTED_MARKER')
    if after['exit_code'] != 0:
        return 'BLOCKED_AFTER_COMMAND_FAILED', observations + ['AFTER_NONZERO_EXIT']
    if failure_marker in after['log_text']:
        return 'UNKNOWN_AFTER_RETAINS_FAILURE_MARKER', observations + ['FAILURE_MARKER_STILL_PRESENT']
    if artifact_marker not in after['log_text']:
        return 'UNKNOWN_AFTER_ARTIFACT_MARKER_MISSING', observations + ['AFTER_ARTIFACT_MARKER_NOT_OBSERVED']
    return 'SCOPED_COMMAND_EVIDENCE_PASS', observations + [
        'AFTER_EXIT_ZERO', 'AFTER_LOG_CONTAINS_ARTIFACT_MARKER_UNATTESTED',
        'NOT_FULL_ANDROID_RELEASE_PROOF',
    ]


def verify(manifest: Path, workspace: Path, output: Path, timeout: int, *, execute: bool) -> dict:
    if not execute:
        raise ValueError('EXPLICIT_EXECUTE_FLAG_REQUIRED')
    doc = load_manifest(manifest)
    if not workspace.is_dir() or workspace.is_symlink():
        raise ValueError('WORKSPACE_ROOT_INVALID')
    workspace = workspace.resolve()
    for arm in doc['runs'].values():
        require_inside(workspace, arm['cwd'], require_dir=True)
    before_dir = require_inside(workspace, doc['runs']['before']['cwd'])
    after_dir = require_inside(workspace, doc['runs']['after']['cwd'])
    if before_dir == after_dir:
        raise ValueError('BEFORE_AFTER_WORKSPACES_MUST_DIFFER')
    if any(root in output.resolve().parents or root == output.resolve() for root in (before_dir, after_dir)):
        raise ValueError('OUTPUT_CANNOT_BE_INSIDE_ARM_WORKSPACE')
    if output.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    output.mkdir(parents=True)
    raw_before = run_arm(doc['runs']['before'], workspace, output, 'before', timeout)
    raw_after = run_arm(doc['runs']['after'], workspace, output, 'after', timeout)
    status, observations = classify(raw_before, raw_after, doc['failure_marker'], doc['after_artifact_marker'])
    for arm in (raw_before, raw_after):
        arm['failure_marker_seen'] = doc['failure_marker'] in arm['log_text']
        arm['artifact_marker_seen'] = doc['after_artifact_marker'] in arm['log_text']
        del arm['log_text']
    result = {
        'schema_version': SCHEMA,
        'case_id': doc['case_id'],
        'scope': doc['scope'],
        'status': status,
        'observations': observations,
        'upstream_references': doc.get('upstream_references', []),
        'runs': {'before': raw_before, 'after': raw_after},
        'limitations': [
            'Commands are supplied by developer; they are not automatically proven to compile an entire app.',
            'Artifact markers are textual observations in logs, not attested resolved dependency graphs.',
            'No runtime, APK/AAB, native binary, Google Play or full release certification.',
            'Command execution can download dependencies and write to the selected workspaces.',
        ],
    }
    (output / 'report.json').write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    return result


def self_test() -> None:
    successes = 0
    with tempfile.TemporaryDirectory(prefix='workbench-alpha-') as t:
        base = Path(t)
        ws = base / 'sandboxes'
        (ws / 'before').mkdir(parents=True)
        (ws / 'after').mkdir(parents=True)
        for role in ('before', 'after'):
            (ws / role / 'build.gradle.kts').write_text('plugin {}', encoding='utf-8')
        m = {
            'schema_version':'rn-upgrade-case-0.1',
            'case_id':'SYNTHETIC_SMOKE_ONLY',
            'scope':'user_defined_command',
            'failure_marker':'SYNTHETIC_ABSTRACT_METHOD_ERROR',
            'after_artifact_marker':'SYNTHETIC_ARTIFACT_0.2.0',
            'runs': {
                'before':{'cwd':'before','sources':['build.gradle.kts'],'argv':[sys.executable, '-c', 'print("SYNTHETIC_ABSTRACT_METHOD_ERROR"); raise SystemExit(1)']},
                'after':{'cwd':'after','sources':['build.gradle.kts'],'argv':[sys.executable, '-c', 'print("SYNTHETIC_ARTIFACT_0.2.0")']},
            },
        }
        manifest = base / 'case.json'
        manifest.write_text(json.dumps(m), encoding='utf-8')
        report = verify(manifest, ws, base / 'run1', 10, execute=True)
        assert report['status'] == 'SCOPED_COMMAND_EVIDENCE_PASS'
        assert (base / 'run1' / 'before.log').exists()
        successes += 1
        m['runs']['before']['argv'] = [sys.executable, '-c', 'print("SYNTHETIC_ABSTRACT_METHOD_ERROR")']
        manifest.write_text(json.dumps(m), encoding='utf-8')
        assert verify(manifest, ws, base/'run2', 10, execute=True)['status'] == 'UNKNOWN_BEFORE_FAILURE_NOT_REPRODUCED'
        successes += 1
        m['runs']['before']['argv'] = [sys.executable, '-c', 'print("UNRELATED_SDK_LOCATION_FAILURE"); raise SystemExit(1)']
        manifest.write_text(json.dumps(m), encoding='utf-8')
        assert verify(manifest, ws, base/'run3', 10, execute=True)['status'] == 'UNKNOWN_BEFORE_DIFFERENT_FAILURE'
        successes += 1
        m['runs']['before']['argv'] = [sys.executable, '-c', 'print("SYNTHETIC_ABSTRACT_METHOD_ERROR"); raise SystemExit(1)']
        m['runs']['after']['argv'] = [sys.executable, '-c', 'print("AFTER_COMMAND_SUCCESS")']
        manifest.write_text(json.dumps(m), encoding='utf-8')
        assert verify(manifest, ws, base/'run4', 10, execute=True)['status'] == 'UNKNOWN_AFTER_ARTIFACT_MARKER_MISSING'
        successes += 1
        m['runs']['after']['argv'] = [sys.executable, '-c', 'print("SYNTHETIC_ABSTRACT_METHOD_ERROR SYNTHETIC_ARTIFACT_0.2.0")']
        manifest.write_text(json.dumps(m), encoding='utf-8')
        assert verify(manifest, ws, base/'run5', 10, execute=True)['status'] == 'UNKNOWN_AFTER_RETAINS_FAILURE_MARKER'
        successes += 1
        m['runs']['after']['argv'] = [sys.executable, '-c', 'print("SYNTHETIC_ARTIFACT_0.2.0"); raise SystemExit(1)']
        manifest.write_text(json.dumps(m), encoding='utf-8')
        assert verify(manifest, ws, base/'run6', 10, execute=True)['status'] == 'BLOCKED_AFTER_COMMAND_FAILED'
        successes += 1
        m['runs']['after']['cwd'] = 'before'
        manifest.write_text(json.dumps(m), encoding='utf-8')
        try:
            verify(manifest, ws, base/'run7', 10, execute=True)
        except ValueError as e:
            assert str(e) == 'BEFORE_AFTER_WORKSPACES_MUST_DIFFER'
        else:
            raise AssertionError('Identical workspace accepted')
        successes += 1
        m['runs']['after']['cwd'] = '../outside'
        manifest.write_text(json.dumps(m), encoding='utf-8')
        try:
            verify(manifest, ws, base/'run8', 10, execute=True)
        except ValueError as e:
            assert str(e) == 'PATH_TRAVERSAL_FORBIDDEN'
        else:
            raise AssertionError('Traversal accepted')
        successes += 1
        from expo_kotlin_preflight import make_fixture
        app = make_fixture(base, '0.1.5')
        assert evaluate(app, '2.3.20')['finding'] == 'KNOWN_HISTORICAL_RISK_PAIR'
        successes += 1
        app = make_fixture(base, '0.2.5')
        assert evaluate(app, '2.3.20')['finding'] == 'OLD_0_1_5_SIGNATURE_ABSENT_NOT_CERTIFIED_SAFE'
        successes += 1
    print(f'WORKBENCH_SELF_TEST: PASS {successes}/10 (synthetic command evidence; not Gradle)')


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='RN Upgrade Workbench alpha (not a release certification)')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('self-test')
    pre = sub.add_parser('preflight', help='Source-only narrow Expo/Kotlin preflight, no build')
    pre.add_argument('--app', type=Path, required=True)
    pre.add_argument('--target-kgp', required=True)
    pre.add_argument('--json', action='store_true')
    replay = sub.add_parser('replay-expo', help='Audit saved historical Expo #50293 evidence; no Gradle execution')
    replay.add_argument('--old-evidence', type=Path, required=True)
    replay.add_argument('--fixed-evidence', type=Path, required=True)
    replay.add_argument('--output', type=Path, required=True)
    native = sub.add_parser('inspect-native', help='Read-only ELF PT_LOAD and APK 16 KB ZIP alignment evidence')
    native.add_argument('--artifact', type=Path, required=True)
    native.add_argument('--json', action='store_true')
    prov_prepare = sub.add_parser('native-provenance-prepare', help='Stage a minimal Gradle consumer for pinned AAR provenance')
    prov_prepare.add_argument('--artifact', type=Path, required=True)
    prov_prepare.add_argument('--coordinate', required=True)
    prov_prepare.add_argument('--output-root', type=Path, required=True)
    prov_assess = sub.add_parser('native-provenance-assess', help='Compare saved Gradle AAR resolution with local AAR and its .so files')
    prov_assess.add_argument('--case', type=Path, required=True)
    prov_assess.add_argument('--gradle-log', type=Path, required=True)
    prov_assess.add_argument('--gradle-exit-code', type=int, required=True)
    prov_assess.add_argument('--artifact', type=Path, required=True)
    prov_assess.add_argument('--output', type=Path, required=True)
    v = sub.add_parser('verify', help='Run explicit before/after commands in separate prepared workspaces')
    v.add_argument('--manifest', type=Path, required=True)
    v.add_argument('--workspace', type=Path, required=True)
    v.add_argument('--output', type=Path, required=True)
    v.add_argument('--timeout', type=int, default=600)
    v.add_argument('--execute', action='store_true', help='Explicitly acknowledge arbitrary subprocess execution')
    args = p.parse_args(argv)
    try:
        if args.command == 'self-test':
            self_test()
        elif args.command == 'preflight':
            doc = evaluate(args.app, args.target_kgp)
            if args.json:
                print(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False))
            else:
                for key in ('installed_expo_gradle_plugin','proposed_target_kgp','finding','compatibility_verdict','release_readiness'):
                    print(f'{key.upper()}: {doc[key]}')
                for e in doc['plugin_evidence']:
                    print(f"EVIDENCE: {e['source']}:{e['line']} plugin={e['value']}")
        elif args.command == 'native-provenance-prepare':
            from native_provenance import prepare
            prepared = prepare(args.artifact, args.coordinate, args.output_root)
            print('NATIVE_PROVENANCE_PREPARED:', prepared['case_file'])
            print('GRADLE_PROJECT:', prepared['gradle_project'])
            print('EXPECTED_AAR_SHA256:', prepared['artifact_sha256'])
            print('REAL_GRADLE_RUN_NOT_PERFORMED: True')
        elif args.command == 'native-provenance-assess':
            from native_provenance import assess
            report = assess(args.case, args.gradle_log, args.artifact, gradle_exit_code=args.gradle_exit_code)
            if args.output.exists():
                raise ValueError('OUTPUT_ALREADY_EXISTS')
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)+'\n', encoding='utf-8')
            print('NATIVE_PROVENANCE_STATUS:', report['status'])
            print('CHECKS:',sum(report['checks'].values()),'/',len(report['checks']))
            if report['native_summary']:
                print('NATIVE_ENTRIES:', report['native_summary']['native_library_count'])
            print('APPLICATION_OWNER:', report['actual_app_dependency_owner'])
            print('REPORT:', args.output)
            return 0 if report['status'] == 'SCOPED_GRADLE_AAR_PROVENANCE_MATCH' else 3
        elif args.command == 'inspect-native':
            from inspect_native_artifact import inspect
            report = inspect(args.artifact)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
            else:
                print('NATIVE_STATUS:', report['status'])
                print('ARTIFACT:', report['artifact_name'])
                print('ARTIFACT_SHA256:', report['artifact_sha256'])
                print('SO_ENTRIES:', report['native_library_count'])
                print('ALIGNMENT_SUMMARY:', json.dumps(report['alignment_summary'], sort_keys=True))
                for item in report['libraries']:
                    print('LIB:', item['entry'], 'ABI:', item.get('abi_from_archive_path'),
                          'ELF:', item['elf']['status'], 'APK_ZIP:', item['apk_zip_16k'])
                    for ph in item['elf'].get('segments', []):
                        print('  PT_LOAD:', ph['index'], 'p_align:', ph['p_align'],
                              'aligned_16k:', ph['aligned_16k'])
                print('MAVEN_OWNER: NOT_VERIFIED')
                print('SCOPE: ELF program-header and APK ZIP offsets only; not release readiness')
            return (2 if report['status'].startswith('ATTENTION_') else
                    3 if report['status'].startswith(('UNKNOWN_', 'NOT_EVALUATED_')) else 0)
        elif args.command == 'replay-expo':
            from replay_expo_evidence import evaluate as replay
            result = replay(args.old_evidence, args.fixed_evidence)
            if args.output.exists():
                raise ValueError('OUTPUT_ALREADY_EXISTS')
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)+'\n', encoding='utf-8')
            print('REPLAY_STATUS:', result['status'])
            print('CHECKS:', sum(result['checks'].values()), '/', len(result['checks']))
            print('REPORT:', args.output)
            return 0 if result['status'] == 'REPLAYED_HISTORICAL_EVIDENCE_CONSISTENT' else 3
        elif args.command == 'verify':
            if not 1 <= args.timeout <= 3600:
                raise ValueError('TIMEOUT_MUST_BE_1_TO_3600_SECONDS')
            out = verify(args.manifest, args.workspace, args.output, args.timeout, execute=args.execute)
            print('CASE:', out['case_id'])
            print('STATUS:', out['status'])
            print('SCOPE:', out['scope'])
            print('EVIDENCE_REPORT:', args.output / 'report.json')
            return 0 if out['status'] == 'SCOPED_COMMAND_EVIDENCE_PASS' else 3
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f'INPUT_OR_EXECUTION_ERROR: {exc}', file=sys.stderr)
        return 4
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
