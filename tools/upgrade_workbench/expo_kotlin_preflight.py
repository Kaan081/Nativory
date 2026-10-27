#!/usr/bin/env python3
"""EXPO-KOTLIN-PREFLIGHT-01 — isolated read-only proposed-upgrade experiment.

Standalone: Python >=3.10 standard library only; no other scripts required.
No network, Gradle/Node subprocesses, package installs, application writes,
or repository modifications. This does NOT establish effective compiler versions
or certify upgrade safety. It only matches ONE reproduced historical risk pair.

  py -B rn_expo_kotlin_target_preflight_v2_standalone.py --self-test
  py -B rn_expo_kotlin_target_preflight_v2_standalone.py --app APP --target-kgp 2.3.20
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

MAX_SOURCE_BYTES = 3_000_000
EXPO_PLUGIN_SRC = "node_modules/expo-modules-core/expo-module-gradle-plugin/build.gradle.kts"
EXPO_VAR_SRC = "node_modules/expo-modules-core/android/build.gradle"
PLUGIN_DEP_PATTERN = re.compile(
    r'\bimplementation\s*\(\s*["\']io\.github\.expo:expo-modules-v2-gradle-plugin:'
    r'(\d+(?:\.\d+){2,3})["\']\s*\)'
)
PLUGIN_VARIABLE_PATTERN = re.compile(
    r'\bexpoModulesV2Version\s*=\s*["\'](\d+(?:\.\d+){2,3})["\']'
)
KGP_TARGET_PATTERN = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z')
ISSUE_URL = "https://github.com/expo/expo/issues/50293"
FIX_URL = "https://github.com/expo/expo/pull/50562"


def read_source(root: Path, rel: str) -> tuple[str, str | None, str | None]:
    """Conservative bounded read; refuse symlinked paths rather than following them."""
    source = root
    for part in Path(rel).parts:
        source = source / part
        if source.is_symlink():
            return "UNSUPPORTED_SYMLINK", None, None
    try:
        if not source.is_file():
            return "ABSENT_OR_NOT_REGULAR", None, None
        if source.stat().st_size > MAX_SOURCE_BYTES:
            return "OVERSIZE", None, None
        raw = source.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            return "OVERSIZE", None, None
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            decoded = raw.decode('utf-16')
        else:
            decoded = raw.decode('utf-8-sig')
        if '\x00' in decoded:
            return "UNSUPPORTED_ENCODING", None, None
        return "READ", decoded, hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError):
        return "UNREADABLE_OR_INVALID_ENCODING", None, None


def literal_occurrences(source: str, pattern: re.Pattern[str], rel: str) -> list[dict]:
    """Narrow literal detector only; NOT a Groovy or Kotlin evaluator."""
    without_comments = re.sub(
        r'/\*.*?\*/|//[^\n]*',
        lambda m: re.sub(r'[^\n]', ' ', m.group(0)),
        source,
        flags=re.DOTALL,
    )
    return [
        {"source": rel, "line": without_comments.count('\n', 0, m.start()) + 1, "value": m.group(1)}
        for m in pattern.finditer(without_comments)
    ]


def installed_plugin_evidence(app: Path) -> dict:
    if not app.is_dir() or app.is_symlink():
        raise ValueError('APP_NOT_REGULAR_DIRECTORY')
    app = app.resolve()
    direct_state, direct_content, direct_sha = read_source(app, EXPO_PLUGIN_SRC)
    var_state, var_content, var_sha = read_source(app, EXPO_VAR_SRC)
    direct = literal_occurrences(direct_content, PLUGIN_DEP_PATTERN, EXPO_PLUGIN_SRC) if direct_content else []
    indirect = literal_occurrences(var_content, PLUGIN_VARIABLE_PATTERN, EXPO_VAR_SRC) if var_content else []
    direct_values = {e['value'] for e in direct}
    indirect_values = {e['value'] for e in indirect}
    if direct_state != 'READ' or len(direct) != 1:
        status, version = 'UNKNOWN_EXPO_PLUGIN_DECLARATION', None
    elif (var_state not in ('READ', 'ABSENT_OR_NOT_REGULAR')):
        status, version = 'UNKNOWN_EXPO_PLUGIN_SOURCE_COVERAGE', None
    elif len(direct_values) != 1 or (indirect_values and (len(indirect) != 1 or indirect_values != direct_values)):
        status, version = 'CONFLICTING_EXPO_PLUGIN_DECLARATIONS', None
    else:
        status, version = 'UNIQUE_INSTALLED_DECLARATION', next(iter(direct_values))
    return {
        'version': version,
        'status': status,
        'declarations': direct,
        'related_declarations': indirect,
        'source_status': {EXPO_PLUGIN_SRC: direct_state, EXPO_VAR_SRC: var_state},
        'sha256': {EXPO_PLUGIN_SRC: direct_sha, EXPO_VAR_SRC: var_sha},
    }


def evaluate(app: Path, target: str) -> dict:
    if not KGP_TARGET_PATTERN.fullmatch(target):
        raise ValueError('INVALID_TARGET_KGP_VERSION: expected exact X.Y.Z, e.g. 2.3.20')
    source = installed_plugin_evidence(app)
    plugin = source['version']
    if plugin is None:
        finding = 'UNKNOWN_INSTALLED_EXPO_PLUGIN'
    elif plugin == '0.1.5' and target == '2.3.20':
        finding = 'KNOWN_HISTORICAL_RISK_PAIR'
    elif plugin == '0.1.5' and target == '2.2.10':
        finding = 'REPRODUCED_HISTORICAL_CONTROL_PAIR'
    elif plugin == '0.1.5':
        finding = 'UNKNOWN_UNTESTED_TARGET_FOR_OLD_PLUGIN'
    else:
        finding = 'OLD_0_1_5_SIGNATURE_ABSENT_NOT_CERTIFIED_SAFE'
    return {
        'schema_version': 'EXPO_KOTLIN_PROPOSED_UPGRADE_V2_STANDALONE_EXPERIMENT',
        'scope': 'ONE_HISTORICAL_EXPO_COMPILER_PLUGIN_INCIDENT_ONLY',
        'installed_expo_gradle_plugin': plugin,
        'installed_plugin_resolution_status': source['status'],
        'plugin_evidence': source['declarations'],
        'related_evidence': source['related_declarations'],
        'source_status': source['source_status'],
        'source_sha256': source['sha256'],
        'proposed_target_kgp': target,
        'target_provenance': 'USER_PROPOSED_UPGRADE_NOT_EFFECTIVE_GRADLE_VERSION',
        'finding': finding,
        'rule_evidence': {
            'reproduced_failure_pair': {'expo_gradle_plugin': '0.1.5', 'kgp': '2.3.20'},
            'reproduced_control_pair': {'expo_gradle_plugin': '0.1.5', 'kgp': '2.2.10'},
            'upstream_issue': ISSUE_URL,
            'upstream_remedy': FIX_URL,
        },
        'effective_kgp': 'NOT_VERIFIED',
        'selected_compiler_plugin_artifact': 'NOT_VERIFIED',
        'compatibility_verdict': 'NOT_EVALUATED',
        'release_readiness': 'NOT_VERIFIED',
        'limitations': [
            'Reads an installed Expo Gradle-plugin DEPENDENCY declaration, not Gradle-selected compiler artifacts.',
            'Proposed Kotlin target is an intention, not the effective or resolved version.',
            'A missing historical risk signature does not mean the proposed upgrade is safe.',
            'Only historical exact pairs 0.1.5+2.3.20 and 0.1.5+2.2.10 were reproduced.',
            'No Gradle/Node execution, download, package install, repair or repository modification.',
        ],
    }


def make_fixture(root: Path, plugin: str, variable: str | None = None) -> Path:
    app = root / 'fixture-app'
    dep = app / EXPO_PLUGIN_SRC
    var = app / EXPO_VAR_SRC
    dep.parent.mkdir(parents=True, exist_ok=True)
    var.parent.mkdir(parents=True, exist_ok=True)
    dep.write_text(f'implementation("io.github.expo:expo-modules-v2-gradle-plugin:{plugin}")\n', encoding='utf-8')
    var.write_text(f'def expoModulesV2Version = "{variable or plugin}"\n', encoding='utf-8')
    return app


def self_test() -> None:
    checks = [
        ('0.1.5', '2.3.20', 'KNOWN_HISTORICAL_RISK_PAIR'),
        ('0.1.5', '2.2.10', 'REPRODUCED_HISTORICAL_CONTROL_PAIR'),
        ('0.1.5', '2.3.21', 'UNKNOWN_UNTESTED_TARGET_FOR_OLD_PLUGIN'),
        ('0.2.0', '2.3.20', 'OLD_0_1_5_SIGNATURE_ABSENT_NOT_CERTIFIED_SAFE'),
        ('0.2.5', '2.3.20', 'OLD_0_1_5_SIGNATURE_ABSENT_NOT_CERTIFIED_SAFE'),
    ]
    count = 0
    for plugin, target, expected in checks:
        with tempfile.TemporaryDirectory(prefix='rn-expo-target-') as tmp:
            app = make_fixture(Path(tmp), plugin)
            original = (app / EXPO_PLUGIN_SRC).read_bytes()
            first, second = evaluate(app, target), evaluate(app, target)
            assert first['finding'] == expected, (target, plugin, first['finding'])
            assert first == second
            assert first['compatibility_verdict'] == 'NOT_EVALUATED'
            assert (app / EXPO_PLUGIN_SRC).read_bytes() == original
            count += 1
    with tempfile.TemporaryDirectory(prefix='rn-expo-target-') as tmp:
        app = make_fixture(Path(tmp), '0.1.5')
        dep = app / EXPO_PLUGIN_SRC
        dep.write_text('// ' + dep.read_text(encoding='utf-8'), encoding='utf-8')
        assert evaluate(app, '2.3.20')['finding'] == 'UNKNOWN_INSTALLED_EXPO_PLUGIN'
        count += 1
    with tempfile.TemporaryDirectory(prefix='rn-expo-target-') as tmp:
        app = make_fixture(Path(tmp), '0.1.5', variable='0.2.5')
        assert evaluate(app, '2.3.20')['finding'] == 'UNKNOWN_INSTALLED_EXPO_PLUGIN'
        count += 1
    with tempfile.TemporaryDirectory(prefix='rn-expo-target-') as tmp:
        app = make_fixture(Path(tmp), '0.1.5')
        try:
            evaluate(app, '2.3')
        except ValueError:
            count += 1
        else:
            raise AssertionError('Invalid target version accepted')
    print(f'SELF_TEST: PASS {count}/8')


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path)
    p.add_argument('--target-kgp')
    p.add_argument('--json', action='store_true')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.app or not args.target_kgp:
        p.error('--app and --target-kgp required unless --self-test')
    try:
        report = evaluate(args.app, args.target_kgp)
    except ValueError as error:
        print('INPUT_ERROR: ' + str(error), file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        for field in (
            'scope', 'installed_expo_gradle_plugin', 'installed_plugin_resolution_status',
            'proposed_target_kgp', 'target_provenance', 'finding', 'effective_kgp',
            'selected_compiler_plugin_artifact', 'compatibility_verdict', 'release_readiness',
        ):
            print(f'{field.upper()}: {report[field]}')
        for row in report['plugin_evidence']:
            print(f"EVIDENCE: {row['source']}:{row['line']} plugin={row['value']}")
        print('UPSTREAM_CASE: ' + ISSUE_URL)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
