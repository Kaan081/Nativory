#!/usr/bin/env python3
"""Narrow Gradle AAR artifact -> embedded .so proof for an isolated consumer.

No arbitrary shell execution. prepare creates a NEW minimal Groovy Gradle project;
assess parses a saved Gradle task output and independently hashes both files.
Scope is the generated consumer only, NEVER proof of an external application's graph.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

from inspect_native_artifact import inspect

SCHEMA = 'rn-native-gradle-bridge-0.1'
MARKER = 'RNWB_NATIVE_RESOLUTION_V1:'
COORDINATE = re.compile(r'[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')
MAX_LOG = 16 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 50000:
        raise ValueError('INVALID_CASE_FILE')
    result = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(result, dict) or result.get('schema_version') != SCHEMA:
        raise ValueError('UNSUPPORTED_CASE_SCHEMA')
    return result


def read_log(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_LOG:
        raise ValueError('INVALID_OR_OVERSIZE_GRADLE_LOG')
    raw = path.read_bytes()
    if raw.startswith(b'\xff\xfe'):
        return raw.decode('utf-16')
    if raw.startswith(b'\xfe\xff'):
        return raw.decode('utf-16')
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        # Windows PowerShell 5.1 may save UTF-16LE without BOM.
        if len(raw) % 2 == 0 and raw.count(b'\x00') > len(raw) // 5:
            return raw.decode('utf-16-le')
        raise ValueError('UNSUPPORTED_GRADLE_LOG_ENCODING')


def gradle_script(coordinate: str, nonce: str) -> str:
    group, module, version = coordinate.split(':')
    # Strictly validated fields, no Groovy metacharacters permitted.
    return '''import groovy.json.JsonOutput
import java.security.MessageDigest
import org.gradle.api.artifacts.component.ModuleComponentIdentifier

repositories { mavenCentral() }
configurations {
    proofAar {
        canBeResolved = true
        canBeConsumed = false
        transitive = false
    }
}
dependencies { proofAar("%s@aar") }

tasks.register('rnwbResolveAar') {
    doLast {
        def artifacts = configurations.proofAar.incoming.artifacts.artifacts.toList()
        if (artifacts.size() != 1) throw new GradleException("EXPECTED_ONE_AAR_ARTIFACT")
        def a = artifacts[0]
        def id = a.id.componentIdentifier
        if (!(id instanceof ModuleComponentIdentifier)) throw new GradleException("EXPECTED_MAVEN_COMPONENT_ID")
        if (id.group != "%s" || id.module != "%s" || id.version != "%s") {
            throw new GradleException("RESOLVED_COMPONENT_ID_MISMATCH")
        }
        def file = a.file
        if (!file.name.endsWith('.aar')) throw new GradleException("RESOLVED_NOT_AAR")
        def digest = MessageDigest.getInstance('SHA-256')
        file.withInputStream { stream ->
            byte[] buffer = new byte[65536]
            int n
            while ((n = stream.read(buffer)) != -1) digest.update(buffer, 0, n)
        }
        def hash = digest.digest().collect { String.format('%%02x', it & 0xff) }.join('')
        println('%s' + JsonOutput.toJson([
            schema: 'native-resolution-log-0.1',
            nonce: '%s',
            group: id.group,
            module: id.module,
            version: id.version,
            file: file.absolutePath,
            artifact_sha256: hash,
            artifact_bytes: file.length()
        ]))
    }
}
''' % (coordinate, group, module, version, MARKER, nonce)


def prepare(artifact: Path, coordinate: str, dest: Path) -> dict:
    if not COORDINATE.fullmatch(coordinate):
        raise ValueError('INVALID_EXACT_MAVEN_COORDINATE')
    if artifact.is_symlink() or not artifact.is_file() or artifact.suffix.lower() != '.aar':
        raise ValueError('EXPECTED_EXISTING_AAR_FILE')
    # Let the existing inspector enforce size limits and ZIP integrity where covered.
    inspected = inspect(artifact)
    if dest.exists() or dest.is_symlink():
        raise ValueError('OUTPUT_DESTINATION_MUST_NOT_EXIST')
    dest.mkdir(parents=True, exist_ok=False)
    nonce = uuid.uuid4().hex
    script = gradle_script(coordinate, nonce)
    (dest / 'settings.gradle').write_text("rootProject.name='rnwb-aar-provenance-probe'\n", encoding='utf-8')
    (dest / 'build.gradle').write_text(script, encoding='utf-8')
    case = {
        'schema_version': SCHEMA,
        'scope': 'ISOLATED_GRADLE_CONSUMER_ONLY',
        'coordinate_requested': coordinate,
        'original_artifact_name': artifact.name,
        'original_artifact_sha256': inspected['artifact_sha256'],
        'original_artifact_bytes': artifact.stat().st_size,
        'nonce': nonce,
        'gradle_script_sha256': sha256_file(dest / 'build.gradle'),
        'gradle_settings_sha256': sha256_file(dest / 'settings.gradle'),
        'limitations': [
            'Maven artifact is selected in an isolated generated Gradle consumer, NOT in the Expo app.',
            'Gradle resolution does not prove final APK packaging or runtime loading of any library.',
            'AAR JNI and Prefab source roles must remain distinct; no claim of final APK inclusion.',
            'Resolution output is a developer-run Gradle task log, not a remote attestation.',
        ]
    }
    (dest / 'case.json').write_text(json.dumps(case, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return {'case_file': str(dest / 'case.json'), 'gradle_project': str(dest),
            'artifact_sha256': case['original_artifact_sha256'],
            'command_task': 'rnwbResolveAar'}


def assess(case_path: Path, log_path: Path, original_aar: Path, gradle_exit_code: int | None = None) -> dict:
    case = load_json(case_path)
    if original_aar.is_symlink() or not original_aar.is_file() or original_aar.suffix.lower() != '.aar':
        raise ValueError('INVALID_LOCAL_AAR')
    checks = {}
    checks['case_script_sha256'] = (sha256_file(case_path.parent / 'build.gradle') == case.get('gradle_script_sha256'))
    checks['case_settings_sha256'] = (sha256_file(case_path.parent / 'settings.gradle') == case.get('gradle_settings_sha256'))
    checks['local_aar_sha256'] = (sha256_file(original_aar) == case.get('original_artifact_sha256'))
    checks['local_aar_bytes'] = (original_aar.stat().st_size == case.get('original_artifact_bytes'))
    log_text = read_log(log_path)
    checks['gradle_exit_zero'] = gradle_exit_code == 0
    checks['gradle_build_successful'] = bool(re.search(r'(?m)^BUILD SUCCESSFUL(?:\s|$)', log_text)) and not bool(re.search(r'(?m)^BUILD FAILED(?:\s|$)', log_text))
    marker_lines = [line.split(MARKER, 1)[1].strip() for line in log_text.splitlines()
                    if MARKER in line]
    checks['one_resolution_record'] = len(marker_lines) == 1
    payload = None
    if checks['one_resolution_record']:
        try:
            payload = json.loads(marker_lines[0])
        except (json.JSONDecodeError, ValueError):
            pass
    checks['record_valid_json_object'] = isinstance(payload, dict)
    if not isinstance(payload, dict):
        payload = {}
    checks['record_schema'] = payload.get('schema') == 'native-resolution-log-0.1'
    checks['record_nonce'] = payload.get('nonce') == case.get('nonce')
    checks['resolved_exact_component'] = ':'.join(str(payload.get(x) or '') for x in ('group', 'module', 'version')) == case.get('coordinate_requested')
    claimed_sha = payload.get('artifact_sha256')
    checks['record_sha_format'] = isinstance(claimed_sha, str) and bool(SHA.fullmatch(claimed_sha))
    path_string = payload.get('file')
    try:
        resolved = Path(path_string) if isinstance(path_string, str) else None
        checks['resolved_artifact_file_exists'] = bool(resolved and resolved.is_file() and not resolved.is_symlink() and resolved.suffix.lower()=='.aar')
    except (ValueError, OSError):
        resolved = None
        checks['resolved_artifact_file_exists'] = False
    if checks['resolved_artifact_file_exists']:
        resolved_hash = sha256_file(resolved)
        resolved_bytes = resolved.stat().st_size
    else:
        resolved_hash = None
        resolved_bytes = None
    checks['resolved_file_hash_matches_log'] = bool(resolved_hash and resolved_hash == claimed_sha)
    checks['resolved_file_bytes_match_log'] = (resolved_bytes is not None and resolved_bytes == payload.get('artifact_bytes'))
    checks['resolved_equals_original_aar'] = bool(resolved_hash and resolved_hash == case.get('original_artifact_sha256'))
    all_good = all(checks.values())
    native = inspect(original_aar) if all_good else None
    return {
        'schema_version': SCHEMA,
        'status': 'SCOPED_GRADLE_AAR_PROVENANCE_MATCH' if all_good else 'INCONCLUSIVE_GRADLE_ARTIFACT_PROVENANCE',
        'scope': 'ISOLATED_GRADLE_CONSUMER_ONLY',
        'coordinate_requested': case.get('coordinate_requested'),
        'component_selected_from_gradle_log': ':'.join(str(payload.get(x) or '') for x in ('group', 'module', 'version')) if payload else None,
        'gradle_exit_code_supplied': gradle_exit_code,
        'resolved_aar_sha256': resolved_hash,
        'local_aar_sha256': case.get('original_artifact_sha256'),
        'checks': checks,
        'native_summary': ({'status': native['status'], 'native_library_count': native['native_library_count'],
                            'alignment_summary': native['alignment_summary'],
                            'libraries': [{'entry': x['entry'], 'abi': x.get('abi_from_archive_path'),
                                            'role': x.get('source_role'), 'elf_status': x['elf']['status'],
                                            'sha256': x.get('sha256')} for x in native['libraries']]}
                           if native else None),
        'actual_app_dependency_owner': 'NOT_VERIFIED',
        'final_apk_16k_alignment': 'NOT_VERIFIED',
        'full_android_release_readiness': 'NOT_VERIFIED',
        'limitations': case.get('limitations', []),
    }


def self_test() -> None:
    checks = 0
    with tempfile.TemporaryDirectory(prefix='rnwb-native-bridge-') as t:
        base = Path(t)
        artifact = base / 'test.aar'
        with zipfile.ZipFile(artifact, 'w') as f:
            f.writestr('META-INF/test.txt', 'fixture')
        dest = base / 'probe'
        prep = prepare(artifact, 'com.example:fixture:1.2.3', dest)
        assert prep['command_task'] == 'rnwbResolveAar'
        checks += 1
        case = load_json(dest/'case.json')
        script = (dest/'build.gradle').read_text(encoding='utf-8')
        assert 'proofAar' in script and 'mavenCentral()' in script
        checks += 1
        record = {'schema':'native-resolution-log-0.1', 'nonce':case['nonce'], 'group':'com.example',
                  'module':'fixture', 'version':'1.2.3', 'file': str(artifact),
                  'artifact_sha256':sha256_file(artifact), 'artifact_bytes':artifact.stat().st_size}
        log = base/'saved.log'
        log.write_text('> Task :rnwbResolveAar\n'+MARKER+json.dumps(record)+'\nBUILD SUCCESSFUL\n',encoding='utf-8')
        outcome = assess(dest/'case.json', log, artifact, gradle_exit_code=0)
        assert outcome['status']=='SCOPED_GRADLE_AAR_PROVENANCE_MATCH'
        assert outcome['actual_app_dependency_owner'] == 'NOT_VERIFIED'
        checks += 1
        log.write_bytes(('> Task :rnwbResolveAar\n'+MARKER+json.dumps(record)+'\nBUILD SUCCESSFUL\n').encode('utf-16'))
        assert assess(dest/'case.json', log, artifact, gradle_exit_code=0)['status']=='SCOPED_GRADLE_AAR_PROVENANCE_MATCH'
        checks += 1
        record['nonce'] = 'wrong'
        log.write_text(MARKER+json.dumps(record)+'\n',encoding='utf-8')
        assert assess(dest/'case.json', log, artifact, gradle_exit_code=0)['status'].startswith('INCONCLUSIVE')
        checks += 1
        record['nonce'] = case['nonce']
        record['artifact_sha256'] = 'a'*64
        log.write_text(MARKER+json.dumps(record)+'\n',encoding='utf-8')
        assert not assess(dest/'case.json', log, artifact, gradle_exit_code=0)['checks']['resolved_file_hash_matches_log']
        checks += 1
        record['artifact_sha256'] = sha256_file(artifact)
        record['group'] = 'other'
        log.write_text(MARKER+json.dumps(record)+'\n',encoding='utf-8')
        assert not assess(dest/'case.json', log, artifact, gradle_exit_code=0)['checks']['resolved_exact_component']
        checks += 1
        record['group'] = 'com.example'
        log.write_text(MARKER+json.dumps(record)+'\n'+MARKER+json.dumps(record)+'\n',encoding='utf-8')
        assert not assess(dest/'case.json', log, artifact, gradle_exit_code=0)['checks']['one_resolution_record']
        checks += 1
        log.write_text(MARKER+json.dumps(record)+'\n',encoding='utf-8')
        (dest/'build.gradle').write_text('tampered', encoding='utf-8')
        assert not assess(dest/'case.json', log, artifact, gradle_exit_code=0)['checks']['case_script_sha256']
        checks += 1
        # Even a plausible marker cannot certify a failed Gradle task.
        (dest/'build.gradle').write_text(script, encoding='utf-8')
        log.write_text(MARKER+json.dumps(record)+'\nBUILD SUCCESSFUL in 1s\n', encoding='utf-8')
        assert not assess(dest/'case.json', log, artifact, gradle_exit_code=1)['checks']['gradle_exit_zero']
        checks += 1
        # A marker alone, without Gradle completion, must remain inconclusive.
        log.write_text(MARKER+json.dumps(record)+'\n', encoding='utf-8')
        assert not assess(dest/'case.json', log, artifact, gradle_exit_code=0)['checks']['gradle_build_successful']
        checks += 1
        try:
            prepare(artifact, 'bad:coordinate', base/'invalid')
        except ValueError:
            checks += 1
        else:
            raise AssertionError('INVALID_COORDINATE_ACCEPTED')
    print(f'NATIVE_PROVENANCE_SELF_TEST: PASS {checks}/12 (synthetic Gradle log; not a real Gradle resolution)')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('self-test')
    s = sub.add_parser('prepare')
    s.add_argument('--artifact', type=Path, required=True)
    s.add_argument('--coordinate', required=True)
    s.add_argument('--output-root', type=Path, required=True)
    s = sub.add_parser('assess')
    s.add_argument('--case', type=Path, required=True)
    s.add_argument('--gradle-log', type=Path, required=True)
    s.add_argument('--gradle-exit-code', type=int, required=True)
    s.add_argument('--artifact', type=Path, required=True)
    s.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.command == 'self-test':
            self_test()
        elif a.command == 'prepare':
            print(json.dumps(prepare(a.artifact, a.coordinate, a.output_root), ensure_ascii=False, indent=2))
        else:
            report = assess(a.case, a.gradle_log, a.artifact, gradle_exit_code=a.gradle_exit_code)
            if a.output.exists():
                raise ValueError('OUTPUT_ALREADY_EXISTS')
            a.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+'\n', encoding='utf-8')
            print('NATIVE_PROVENANCE_STATUS:',report['status'])
            print('NATIVE_PROVENANCE_CHECKS:', sum(report['checks'].values()), '/',len(report['checks']))
            print('EVIDENCE_REPORT:', a.output)
            return 0 if report['status']=='SCOPED_GRADLE_AAR_PROVENANCE_MATCH' else 3
        return 0
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as e:
        print('INPUT_ERROR:',e,file=sys.stderr)
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
