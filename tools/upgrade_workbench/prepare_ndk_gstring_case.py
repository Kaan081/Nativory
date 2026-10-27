#!/usr/bin/env python3
"""Prepare two isolated Gradle property-cast probes for Workbench verify.

The broken arm intentionally asserts an inherited NDK property must be readable;
this simulates the bad cast's loss of a GString. It is NOT a native Android build.
No external commands run here. Requires Gradle wrapper only for later verification.
"""
from __future__ import annotations
import argparse
import json
import tempfile
from pathlib import Path

VERSION = '27.1.12297006'
SETTINGS = 'rootProject.name = "ndk-gstring-verification"\ninclude(":consumer")\n'
ROOT = '''// Both before/after Gradle workspaces use the identical Groovy root.
ext.ndkVersion = "${'27.1.12297006'}"
ext.ndkLiteralVersion = '27.1.12297006'
'''
COMMON = '''tasks.register("ndkProbe") {
    doLast {
        val dynamic = rootProject.findProperty("ndkVersion")
        val literal = rootProject.findProperty("ndkLiteralVersion")
        println("PROPERTY_RUNTIME_TYPE: ${dynamic?.javaClass?.name}")
        println("STRING_CONTROL: ${literal as? String ?: "REJECTED"}")
        if (dynamic !is CharSequence || dynamic is String ||
            literal !is String || literal != "27.1.12297006") {
            throw GradleException("FIXTURE_PRECONDITION_NOT_MET")
        }
'''
BEFORE_TAIL = '''        val resolvedNdkVersion = rootProject.findProperty("ndkVersion") as? String
        if (resolvedNdkVersion == null) {
            println("EXPECTED_OLD_GSTRING_CAST_REJECTED")
            throw GradleException("EXPECTED_OLD_GSTRING_CAST_REJECTED")
        }
        throw GradleException("UNEXPECTED_OLD_CAST_ACCEPTED_GSTRING")
    }
}
'''
AFTER_TOP = '''fun org.gradle.api.Project.findRootStringProperty(prop: String): String? =
    (rootProject.findProperty(prop) as? CharSequence)?.toString()?.takeIf { it.isNotEmpty() }

'''
AFTER_TAIL = '''        val resolvedNdkVersion = rootProject.findRootStringProperty("ndkVersion")
        if (resolvedNdkVersion != "27.1.12297006") {
            throw GradleException("PATCHED_PROPERTY_VALUE_MISMATCH")
        }
        println("PATCHED_GSTRING_VALUE=27.1.12297006")
    }
}
'''


def prepare(root: Path, wrapper: Path) -> dict:
    if not wrapper.is_absolute() or not wrapper.is_file() or wrapper.suffix.lower() != '.bat':
        raise ValueError('GRADLEW_BAT_ABSOLUTE_EXISTING_PATH_REQUIRED')
    if root.exists():
        raise ValueError('OUTPUT_ROOT_ALREADY_EXISTS (choose a new folder; never overwrite evidence)')
    root.mkdir(parents=True)
    workspace = root / 'cases'
    for role in ('before', 'after'):
        dest = workspace / role
        (dest / 'consumer').mkdir(parents=True)
        (dest / 'settings.gradle').write_text(SETTINGS, encoding='utf-8', newline='\n')
        (dest / 'build.gradle').write_text(ROOT, encoding='utf-8', newline='\n')
        source = COMMON + (BEFORE_TAIL if role == 'before' else AFTER_TAIL)
        if role == 'after':
            source = AFTER_TOP + source
        (dest / 'consumer' / 'build.gradle.kts').write_text(source, encoding='utf-8', newline='\n')
    cases = {}
    for role in ('before', 'after'):
        cases[role] = {
            'cwd': role,
            'sources': ['settings.gradle', 'build.gradle', 'consumer/build.gradle.kts'],
            'argv': [str(wrapper), '-p', str((workspace / role).resolve()), ':consumer:ndkProbe',
                     '--offline', '--no-daemon', '--console=plain', '--max-workers=2'],
        }
    manifest = {
        'schema_version': 'rn-upgrade-case-0.1',
        'case_id': 'REA-10544-NDK-GSTRING-CAST-SEMANTICS',
        'scope': 'scoped_gradle_task',
        'failure_marker': 'EXPECTED_OLD_GSTRING_CAST_REJECTED',
        'after_artifact_marker': 'PATCHED_GSTRING_VALUE=27.1.12297006',
        'upstream_references': [
            'https://github.com/software-mansion/react-native-reanimated/pull/10544',
            'https://github.com/software-mansion/react-native-reanimated/commit/505638fa0cff03a6230bc59bc061c95d61f1f06d',
        ],
        'runs': cases,
    }
    m = root / 'case.json'
    m.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    return {'manifest': m, 'workspace': workspace, 'report_root': root / 'verification-run-01', 'manifest_data': manifest}


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix='rn-ndk-case-generator-') as td:
        temp = Path(td)
        fake_wrapper = temp / 'gradlew.bat'
        fake_wrapper.write_text('@echo off\r\n', encoding='ascii')
        result = prepare(temp / 'probe', fake_wrapper)
        from workbench import load_manifest
        loaded = load_manifest(result['manifest'])
        assert loaded['case_id'] == 'REA-10544-NDK-GSTRING-CAST-SEMANTICS'
        assert loaded['runs']['before']['argv'][0] == str(fake_wrapper)
        assert (result['workspace'] / 'before' / 'build.gradle').read_bytes() == (
            result['workspace'] / 'after' / 'build.gradle').read_bytes()
        assert 'as? String' in (result['workspace'] / 'before' / 'consumer' / 'build.gradle.kts').read_text()
        assert 'as? CharSequence' in (result['workspace'] / 'after' / 'consumer' / 'build.gradle.kts').read_text()
        assert result['report_root'].exists() is False
        try:
            prepare(temp / 'probe', fake_wrapper)
        except ValueError as exc:
            assert 'OUTPUT_ROOT_ALREADY_EXISTS' in str(exc)
        else:
            raise AssertionError('Generator silently overwrote an existing case')
    print('NDK_CASE_PREPARATION_SELF_TEST: PASS 7/7 (no Gradle run)')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gradlew', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.gradlew or not args.output_root:
        parser.error('--gradlew and --output-root are required')
    try:
        result = prepare(args.output_root.expanduser().resolve(), args.gradlew.expanduser().resolve())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print('CASE_PREPARED:', result['manifest'])
    print('WORKSPACE:', result['workspace'])
    print('REPORT_TARGET:', result['report_root'])
    print('NO_GRADLE_EXECUTED: True')
    print('NEXT: py -B .\\workbench.py verify --manifest "{}" --workspace "{}" --output "{}" --timeout 600 --execute'.format(
        result['manifest'], result['workspace'], result['report_root']))


if __name__ == '__main__':
    main()
