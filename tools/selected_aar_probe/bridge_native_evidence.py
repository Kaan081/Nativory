#!/usr/bin/env python3
"""Offline, fail-closed binding of Nativory Gradle-selected AAR and ELF inspector reports.

No Gradle invocation and no AAR parsing: this joins two already-created records.
Neither JSON document is a cryptographic attestation of its producer.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKER = 'NATIVORY_SELECTED_AAR_V2:'
SCHEMA = 'nativory-native-evidence-bridge-0.1'
COORDINATE = re.compile(r'[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
MAX_LOG = 8 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
MAX_ENTRIES = 512


class InputError(ValueError):
    """Invalid file or undecodable record, not a compatibility verdict."""


def read_source(path: Path, max_bytes: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise InputError('INPUT_MISSING_OR_SYMLINK')
    if path.stat().st_size > max_bytes:
        raise InputError('INPUT_TOO_LARGE')
    raw = path.read_bytes()
    try:
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            return raw.decode('utf-16')
        if raw.startswith(b'\xef\xbb\xbf'):
            return raw.decode('utf-8-sig')
        if len(raw) % 2 == 0 and raw.count(b'\x00') > len(raw) // 5:
            return raw.decode('utf-16-le')  # Windows PowerShell 5.1 without BOM
        return raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise InputError('UNSUPPORTED_INPUT_ENCODING') from exc


def parse_json(raw: str):
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ValueError as exc:
        raise InputError('INVALID_JSON') from exc


def parse_probe_log(raw: str) -> dict:
    entries = [line[len(MARKER):] for line in raw.splitlines() if line.startswith(MARKER)]
    if len(entries) != 1:
        raise InputError('EXPECTED_EXACTLY_ONE_PROBE_RECORD')
    record = parse_json(entries[0])
    if not isinstance(record, dict):
        raise InputError('PROBE_RECORD_NOT_OBJECT')
    return record


def path_set(paths: object) -> set[str]:
    if not isinstance(paths, list) or len(paths) > MAX_ENTRIES:
        raise ValueError('NATIVE_PATHS_INVALID_OR_TOO_MANY')
    if any(not isinstance(p, str) or not p or not p.lower().endswith('.so') or '\\' in p for p in paths):
        raise ValueError('NATIVE_PATH_INVALID')
    if len(set(paths)) != len(paths):
        raise ValueError('DUPLICATE_NATIVE_PATH')
    return set(paths)


def check_64bit_elf_consistency(libraries: list[dict], summary: dict) -> None:
    """Reject ELF summary claims contradicted by inspector per-entry measurements.

    This checks record consistency, not authenticity or APK packaging.
    """
    observed = []
    abi64 = {'arm64-v8a', 'x86_64'}
    for entry in libraries:
        name = entry['entry']
        abi = entry.get('abi_from_archive_path')
        role = entry.get('source_role')
        if name.startswith('jni/'):
            chunks = name.split('/')
            expected_abi = chunks[1] if len(chunks) == 3 else None
            expected_role = 'AAR_JNI_SOURCE'
        elif name.startswith('prefab/modules/'):
            chunks = name.split('/')
            expected_abi = (chunks[4][8:] if len(chunks) >= 6 and chunks[3] == 'libs'
                            and chunks[4].startswith('android.') else None)
            expected_role = 'AAR_PREFAB_BUILD_INPUT'
        else:
            raise ValueError('UNCLASSIFIED_NATIVE_ENTRY')
        if expected_abi not in {'arm64-v8a', 'x86_64', 'armeabi-v7a', 'x86'} or \
                abi != expected_abi or role != expected_role:
            raise ValueError('NATIVE_ABI_OR_SOURCE_ROLE_CONTRADICTION')
        if abi not in abi64:
            continue
        elf = entry.get('elf')
        if not isinstance(elf, dict) or elf.get('elf_class') != 'ELF64':
            raise ValueError('INVALID_64BIT_ELF_RECORD')
        segments = elf.get('segments')
        if not isinstance(segments, list) or not segments:
            raise ValueError('MISSING_64BIT_LOAD_SEGMENTS')
        flags = []
        for seg in segments:
            if not isinstance(seg, dict):
                raise ValueError('INVALID_ELF_LOAD_SEGMENT')
            align, offset, vaddr, flag = [seg.get(k) for k in
                                          ('p_align', 'offset', 'vaddr', 'aligned_16k')]
            if any(type(v) is not int or v < 0 for v in (align, offset, vaddr)) or type(flag) is not bool:
                raise ValueError('INVALID_ELF_LOAD_SEGMENT')
            calculated = align >= 16384 and (align & (align - 1)) == 0 and (offset - vaddr) % 16384 == 0
            if flag != calculated:
                raise ValueError('ELF_ALIGNMENT_FLAG_CONTRADICTION')
            flags.append(flag)
        expected_status = ('ELF_PT_LOAD_16K_ALIGNED' if all(flags)
                           else 'ATTENTION_ELF_PT_LOAD_UNALIGNED')
        if elf.get('status') != expected_status:
            raise ValueError('ELF_STATUS_CONTRADICTION')
        observed.append(all(flags))
    if not observed or type(summary.get('evaluated_64bit_elf_entries')) is not int or \
            summary['evaluated_64bit_elf_entries'] != len(observed):
        raise ValueError('INSPECTOR_64BIT_ENTRY_COUNT_CONTRADICTION')
    expected = ('OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION'
                if all(observed) else 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE')
    if summary.get('status') != expected:
        raise ValueError('INSPECTOR_64BIT_SUMMARY_CONTRADICTION')


def evaluate(probe: dict, native: dict) -> dict:
    report = {
        'schema_version': SCHEMA,
        'status': 'INCONCLUSIVE_EVIDENCE_GAP_OR_MISMATCH',
        'reason': None,
        'scope': 'APP_SELECTED_AAR_TO_LOCAL_ELF_INSPECTION_ONLY',
        'coordinate': None,
        'artifact_sha256': None,
        'native_entry_count': None,
        'elf_assessment_status': None,
        'apk_packaging_verified': False,
        'runtime_verified': False,
        'third_party_checksum_verified': False,
        'root_cause_or_fix_verified': False,
        'limitations': [
            'Gradle-selected AAR and inspector records are local reports, not independent cryptographic attestation.',
            'Equal AAR hashes and matching native paths do not establish which .so is packaged in an APK/AAB.',
            'ELF PT_LOAD evidence does not certify Android 16 KiB release readiness or runtime behavior.',
            'This bridge does not run Gradle, inspect artifact bytes, identify a root cause, or apply a fix.',
        ],
    }
    try:
        def require(condition: bool, reason: str) -> None:
            if not condition:
                raise ValueError(reason)

        require(isinstance(probe, dict) and isinstance(native, dict), 'REPORT_NOT_OBJECT')
        require(probe.get('schema_version') == 'nativory-selected-aar-probe-0.2', 'PROBE_SCHEMA_MISMATCH')
        require(probe.get('scope') == 'APP_RESOLVED_RUNTIME_AAR_ONLY', 'PROBE_SCOPE_MISMATCH')
        require(probe.get('configuration') in ('debugRuntimeClasspath', 'releaseRuntimeClasspath'), 'UNSUPPORTED_CONFIGURATION')
        require(probe.get('status') == 'SCOPED_APP_SELECTED_AAR_OBSERVED', 'AAR_NOT_SELECTED_OR_UNVERIFIED')
        require(probe.get('reason') == 'EXACT_AAR_SELECTED_AND_OBSERVED', 'PROBE_REASON_CONTRADICTION')
        c = probe.get('requested_coordinate')
        require(isinstance(c, str) and COORDINATE.fullmatch(c) is not None, 'INVALID_COORDINATE')
        require(probe.get('selected_coordinate') == c, 'SELECTED_COORDINATE_MISMATCH')
        require(probe.get('selected_component_versions') == [c.split(':')[2]], 'SELECTED_VERSION_MISMATCH')
        require(all(probe.get(k) == 'NOT_VERIFIED' for k in
                    ('actual_apk_packaging', 'runtime_loading', 'third_party_checksum_match', 'root_cause_or_fix')),
                'PROBE_SCOPE_OVERCLAIM')
        report['coordinate'] = c
        sha = probe.get('artifact_sha256')
        require(isinstance(sha, str) and SHA256.fullmatch(sha) is not None, 'INVALID_PROBE_SHA256')
        require(isinstance(probe.get('artifact_bytes'), int) and not isinstance(probe.get('artifact_bytes'), bool)
                and probe['artifact_bytes'] > 0, 'INVALID_PROBE_ARTIFACT_SIZE')
        require(isinstance(probe.get('artifact_name'), str) and probe['artifact_name'].endswith('.aar'), 'INVALID_PROBE_ARTIFACT_NAME')
        require(isinstance(probe.get('native_entry_count'), int) and not isinstance(probe.get('native_entry_count'), bool)
                and 0 <= probe['native_entry_count'] <= MAX_ENTRIES, 'INVALID_PROBE_NATIVE_COUNT')
        probe_paths = path_set(probe.get('native_entry_paths'))
        require(len(probe_paths) == probe['native_entry_count'], 'PROBE_NATIVE_PATH_COUNT_MISMATCH')

        require(native.get('schema_version') == 'rn-upgrade-native-evidence-0.2', 'INSPECTOR_SCHEMA_MISMATCH')
        require(native.get('artifact_format') == 'aar', 'INSPECTOR_NOT_AAR')
        require(native.get('artifact_name') == probe['artifact_name'], 'ARTIFACT_NAME_MISMATCH')
        require(native.get('artifact_sha256') == sha, 'ARTIFACT_SHA256_MISMATCH')
        require(native.get('size_bytes') == probe['artifact_bytes'], 'ARTIFACT_SIZE_MISMATCH')
        report['artifact_sha256'] = sha
        require(isinstance(native.get('native_library_count'), int) and
                not isinstance(native.get('native_library_count'), bool), 'INVALID_INSPECTOR_COUNT')
        require(native.get('native_library_count') == probe['native_entry_count'], 'NATIVE_COUNT_MISMATCH')
        libs = native.get('libraries')
        require(isinstance(libs, list), 'INVALID_INSPECTOR_LIBRARIES')
        inspect_paths = path_set([x.get('entry') if isinstance(x, dict) else None for x in libs])
        require(len(inspect_paths) == native['native_library_count'], 'INSPECTOR_PATH_COUNT_MISMATCH')
        require(probe_paths == inspect_paths, 'NATIVE_ENTRY_PATHS_MISMATCH')
        report['native_entry_count'] = len(probe_paths)

        summary = native.get('alignment_summary')
        require(isinstance(summary, dict), 'INSPECTOR_SUMMARY_MISSING')
        check_64bit_elf_consistency(libs, summary)
        elf_status = summary.get('status')
        require(isinstance(elf_status, str) and native.get('status') == elf_status, 'INSPECTOR_STATUS_CONTRADICTION')
        require(summary.get('runtime_or_release_certified') is False and
                summary.get('apk_zip_certified_by_official_zipalign') is False, 'INSPECTOR_SCOPE_OVERCLAIM')
        report['elf_assessment_status'] = elf_status
        require(isinstance(summary.get('evaluated_64bit_elf_entries'), int) and
                summary.get('evaluated_64bit_elf_entries') > 0, 'NO_EVALUATED_64BIT_ELF')
        require(elf_status in ('OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION',
                               'ATTENTION_64BIT_ALIGNMENT_EVIDENCE'), 'ELF_EVIDENCE_NOT_CONCLUSIVE')
        report['status'] = 'SCOPED_AAR_NATIVE_EVIDENCE_LINKED_NOT_RELEASE_CERTIFIED'
        report['reason'] = 'SHA256_SIZE_PATHS_AND_ELF_SUMMARY_CONSISTENT'
    except (ValueError, TypeError, KeyError) as exc:
        report['reason'] = str(exc) if isinstance(exc, ValueError) else 'INVALID_EVIDENCE_STRUCTURE'
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe-log', type=Path, required=True)
    p.add_argument('--inspection-json', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        p.error('OUTPUT_ALREADY_EXISTS')
    try:
        probe = parse_probe_log(read_source(args.probe_log, MAX_LOG))
        native = parse_json(read_source(args.inspection_json, MAX_JSON))
        report = evaluate(probe, native)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write('\n')
    except (InputError, OSError, FileExistsError) as exc:
        print('INPUT_ERROR: ' + str(exc), file=sys.stderr)
        return 4
    print(report['status'], report['reason'])
    return 0 if report['status'] == 'SCOPED_AAR_NATIVE_EVIDENCE_LINKED_NOT_RELEASE_CERTIFIED' else 2


if __name__ == '__main__':
    sys.exit(main())
