#!/usr/bin/env python3
"""Correlate independently recorded *scoped* FBJNI evidence; never certify an app fix.

Inputs are diagnostic records, not trusted cryptographic attestations. This script
checks consistency but cannot prove the tool that generated a record was honest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = 'rnwb-fix-evidence-bridge-0.1'
POSITIVE = 'SCOPED_CROSS_SOURCE_EVIDENCE_VERIFIED_NOT_APP_FIX'
UNKNOWN = 'INCONCLUSIVE_EVIDENCE_GAP_OR_CONTRADICTION'
EXPECTED = 'com.facebook.fbjni:fbjni:0.7.0'
ABIS_64 = {'arm64-v8a', 'x86_64'}
MAX_INPUT = 1_000_000


def load(root: Path, name: str, *, json_file: bool = False):
    path = root / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT:
        raise ValueError('MISSING_OR_OVERSIZED:' + name)
    text = path.read_text(encoding='utf-8')
    return json.loads(text) if json_file else text


def check(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def records(report: dict) -> dict[str, dict]:
    check(report.get('artifact_format') == 'aar', 'NOT_AN_AAR_REPORT')
    paths = {}
    for item in report['libraries']:
        path = item['entry']
        check(path not in paths, 'DUPLICATE_NATIVE_PATH')
        paths[path] = item
    check(len(paths) == report.get('native_library_count'), 'NATIVE_ENTRY_COUNT_MISMATCH')
    return paths


def check_elf_pair(before: dict, after: dict, independent: dict) -> tuple[int, int]:
    expected_status = {
        '0.6.0': 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE',
        '0.7.0': 'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION',
    }
    for version, report in (('0.6.0', before), ('0.7.0', after)):
        check(report.get('status') == expected_status[version], 'WRONG_WORKBENCH_STATUS_' + version)
        check(report.get('alignment_summary', {}).get('status') == expected_status[version], 'WRONG_ALIGNMENT_SUMMARY_' + version)
        check(report.get('alignment_summary', {}).get('runtime_or_release_certified') is False, 'UNSUPPORTED_RELEASE_CERTIFICATION')
    check(independent.get('status') == 'REAL_64BIT_ELF_NEGATIVE_POSITIVE_OBSERVED', 'INDEPENDENT_PAIR_STATUS_MISMATCH')
    before_paths, after_paths = records(before), records(after)
    check(before_paths.keys() == after_paths.keys(), 'BEFORE_AFTER_NATIVE_PATHS_DIFFER')
    seen = 0
    segments_checked = 0
    for version, originals in (('0.6.0', before_paths), ('0.7.0', after_paths)):
        entries = independent[version]['independent_readelf']
        selected = {p: v for p, v in originals.items() if v.get('abi_from_archive_path') in ABIS_64}
        check(len(entries) == len(selected) and len(selected) > 0, 'INDEPENDENT_64BIT_COUNT_MISMATCH')
        check(independent[version]['verified_64bit_entries'] == len(selected), 'INDEPENDENT_64BIT_TOTAL_MISMATCH')
        seen_paths = set()
        for item in entries:
            path = item['entry']
            check(path in selected and path not in seen_paths, 'INDEPENDENT_ENTRY_UNKNOWN_OR_DUPLICATE')
            seen_paths.add(path)
            elf = selected[path]['elf']
            check(elf.get('elf_class') == 'ELF64', 'NOT_ELF64')
            segments = elf.get('segments', [])
            check(bool(segments), 'NO_PT_LOAD_SEGMENTS')
            aligns = [s['p_align'] for s in segments]
            flags = [s['aligned_16k'] for s in segments]
            check(aligns == item['p_align'], 'READELF_ALIGNMENT_MISMATCH')
            check(all(isinstance(f, bool) for f in flags), 'BAD_SEGMENT_FLAG')
            for segment in segments:
                align = segment['p_align']
                calculated = (isinstance(align, int) and align >= 16384 and
                              (align & (align - 1)) == 0 and
                              (segment['offset'] - segment['vaddr']) % 16384 == 0)
                check(segment['aligned_16k'] is calculated, 'ELF_ALIGNMENT_FLAG_CONTRADICTS_HEADER')
            check(item['all_loads_16k'] is all(flags), 'READELF_BOOLEAN_MISMATCH')
            if version == '0.6.0':
                check(not all(flags), 'BEFORE_64BIT_NOT_NEGATIVE')
            else:
                check(all(flags), 'AFTER_64BIT_NOT_ALIGNED')
            segments_checked += len(segments)
        check(seen_paths == set(selected), 'MISSING_INDEPENDENT_ENTRIES')
        if version == '0.7.0':
            seen = len(selected)
    return seen, segments_checked


def assess(app: Path, pair: Path) -> dict:
    result = {
        'schema_version': SCHEMA,
        'status': UNKNOWN,
        'scope': 'CI_GENERATED_EXPO58_APP_AND_PUBLISHED_MAVEN_AAR_PAIR',
        'limitations': [
            'No before/after dependency graph from the same real app',
            'No actual app fix or resolved APK/AAB packaging verified',
            'No runtime, Play Console or engineer time-savings acceptance',
            'Consistency of recorded evidence is not cryptographic attestation',
        ],
    }
    try:
        code = load(app, 'gradle-exit-code.txt').strip()
        graph = load(app, 'dependency-insight.log')
        selected_log = load(app, 'app-selected-aar.log')
        check(code == '0', 'APP_GRAPH_EXIT_NOT_ZERO')
        check('BUILD SUCCESSFUL' in graph and 'BUILD SUCCESSFUL' in selected_log, 'GRADLE_BUILD_NOT_SUCCESSFUL')
        check(EXPECTED in graph, 'EXPECTED_COMPONENT_ABSENT_FROM_GRAPH')
        check('com.facebook.hermes:hermes-android:' in graph and
              'com.facebook.react:react-android:0.88.0' in graph, 'UPSTREAM_OWNERSHIP_PATH_NOT_SHOWN')
        found = re.findall(r'^RNWB_APP_AAR_PROVENANCE_V1:(\{[^\n]+\})$', selected_log, flags=re.M)
        check(len(found) == 1, 'NO_UNIQUE_APP_SELECTED_AAR_RECORD')
        selected = json.loads(found[0])
        check(selected.get('scope') == 'CI_GENERATED_EXPO58_APP_DEBUG_RUNTIME_ONLY', 'WRONG_APP_SCOPE')
        check(selected.get('status') == 'SCOPED_APP_SELECTED_AAR_MATCH', 'APP_AAR_NOT_MATCHED')
        check(selected.get('coordinate') == EXPECTED, 'APP_SELECTED_COORDINATE_MISMATCH')
        check(selected.get('current_user_local_app_owner') == 'NOT_VERIFIED' and
              selected.get('apk_packaging_and_release') == 'NOT_VERIFIED', 'APP_SCOPE_OVERCLAIM')
        check(selected.get('artifact_bytes', 0) > 0, 'APP_AAR_EMPTY')

        before = load(pair, 'fbjni-0.6.0-workbench.json', json_file=True)
        after = load(pair, 'fbjni-0.7.0-workbench.json', json_file=True)
        independent = load(pair, 'pair-result.json', json_file=True)
        check(before.get('artifact_name') == 'fbjni-0.6.0.aar' and
              after.get('artifact_name') == 'fbjni-0.7.0.aar', 'MAVEN_ARTIFACT_IDENTITY_MISMATCH')
        check(before.get('artifact_sha256') != after.get('artifact_sha256'), 'NO_BEFORE_AFTER_HASH_DIFFERENCE')
        for v, report in (('0.6.0', before), ('0.7.0', after)):
            checksum = load(pair, f'fbjni-{v}.aar.sha256').strip().lower()
            check(bool(re.fullmatch(r'[0-9a-f]{64}', checksum)), 'INVALID_MAVEN_CHECKSUM')
            check(checksum == report['artifact_sha256'], 'MAVEN_WORKBENCH_HASH_MISMATCH')
        check(selected['sha256'] == selected['reference_sha256'] == after['artifact_sha256'], 'APP_AFTER_AAR_HASH_MISMATCH')
        after_paths = records(after)
        check(selected.get('native_entry_count') == len(after_paths) and
              len(set(selected.get('native_entry_paths', []))) == len(after_paths) and
              set(selected['native_entry_paths']) == set(after_paths), 'APP_AAR_NATIVE_PATHS_MISMATCH')
        count, segments = check_elf_pair(before, after, independent)
        result.update({
            'status': POSITIVE, 'app_selected_coordinate': EXPECTED,
            'selected_and_published_after_sha256': selected['sha256'],
            'published_before_sha256': before['artifact_sha256'],
            'paired_64bit_library_paths': count,
            'independently_compared_pt_load_segments_across_both_versions': segments,
            'app_fix_accepted': False, 'release_certified': False,
        })
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, OSError, json.JSONDecodeError) as exc:
        result['reason'] = str(exc) if isinstance(exc, ValueError) else 'INVALID_OR_INCOMPLETE_EVIDENCE_RECORD'
        result['app_fix_accepted'] = False
        result['release_certified'] = False
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app-dir', type=Path, required=True)
    p.add_argument('--pair-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--app-run-id', type=int)
    p.add_argument('--app-head-sha')
    p.add_argument('--pair-run-id', type=int)
    p.add_argument('--pair-head-sha')
    args = p.parse_args()
    if args.output.exists():
        p.error('OUTPUT_ALREADY_EXISTS')
    result = assess(args.app_dir, args.pair_dir)
    result['source_runs_as_asserted_by_invoker'] = {
        'app': {'run_id': args.app_run_id, 'head_sha': args.app_head_sha},
        'published_pair': {'run_id': args.pair_run_id, 'head_sha': args.pair_head_sha},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(result['status'], result.get('reason', ''))
    return 0 if result['status'] == POSITIVE else 2


if __name__ == '__main__':
    sys.exit(main())
