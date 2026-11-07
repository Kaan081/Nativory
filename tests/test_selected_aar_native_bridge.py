"""No Gradle/network. Synthetic bridge contract and fail-closed regressions."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parents[1] / 'tools' / 'selected_aar_probe' / 'bridge_native_evidence.py'
spec = importlib.util.spec_from_file_location('nativory_native_bridge', MODULE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

SHA = '7e319ae110ac5e5ef18904170aea5c3e753e915d196699d7fd39d36c8e1dfe36'


def examples():
    paths = ['jni/arm64-v8a/libfbjni.so', 'prefab/modules/fbjni/libs/android.arm64-v8a/libfbjni.so']
    p = {
        'schema_version': 'nativory-selected-aar-probe-0.2',
        'scope': 'APP_RESOLVED_RUNTIME_AAR_ONLY',
        'configuration': 'debugRuntimeClasspath',
        'status': 'SCOPED_APP_SELECTED_AAR_OBSERVED',
        'reason': 'EXACT_AAR_SELECTED_AND_OBSERVED',
        'requested_coordinate': 'com.facebook.fbjni:fbjni:0.7.0',
        'selected_coordinate': 'com.facebook.fbjni:fbjni:0.7.0',
        'selected_component_versions': ['0.7.0'],
        'artifact_name': 'fbjni-0.7.0.aar',
        'artifact_sha256': SHA,
        'artifact_bytes': 4349156,
        'native_entry_count': 2,
        'native_entry_paths': paths,
        'actual_apk_packaging': 'NOT_VERIFIED',
        'runtime_loading': 'NOT_VERIFIED',
        'third_party_checksum_match': 'NOT_VERIFIED',
        'root_cause_or_fix': 'NOT_VERIFIED'
    }
    n = {
        'schema_version': 'rn-upgrade-native-evidence-0.2',
        'artifact_format': 'aar',
        'artifact_name': p['artifact_name'],
        'artifact_sha256': SHA,
        'size_bytes': 4349156,
        'native_library_count': 2,
        'libraries': [{'entry': x, 'abi_from_archive_path': 'arm64-v8a',
                       'source_role': ('AAR_JNI_SOURCE' if x.startswith('jni/') else 'AAR_PREFAB_BUILD_INPUT'),
                       'elf': {'status': 'ELF_PT_LOAD_16K_ALIGNED', 'elf_class': 'ELF64',
                               'segments': [{'p_align': 16384, 'offset': 0, 'vaddr': 0, 'aligned_16k': True}]}}
                      for x in paths],
        'status': 'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION',
        'alignment_summary': {
            'status': 'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION',
            'evaluated_64bit_elf_entries': 2,
            'runtime_or_release_certified': False,
            'apk_zip_certified_by_official_zipalign': False
        }
    }
    return p, n


def status(p, n):
    return bridge.evaluate(p, n)['status']


def test_positive_identity_and_alignment_scope():
    p, n = examples()
    report = bridge.evaluate(p, n)
    assert report['status'] == 'SCOPED_AAR_NATIVE_EVIDENCE_LINKED_NOT_RELEASE_CERTIFIED'
    assert report['coordinate'] == p['requested_coordinate']
    assert report['artifact_sha256'] == SHA
    assert not report['apk_packaging_verified']
    assert not report['runtime_verified']
    assert not report['third_party_checksum_verified']


def test_attention_is_evidence_not_release_certification():
    p, n = examples()
    n['libraries'][0]['elf']['segments'][0]['p_align'] = 4096
    n['libraries'][0]['elf']['segments'][0]['aligned_16k'] = False
    n['libraries'][0]['elf']['status'] = 'ATTENTION_ELF_PT_LOAD_UNALIGNED'
    n['status'] = n['alignment_summary']['status'] = 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE'
    result = bridge.evaluate(p, n)
    assert result['status'] == 'SCOPED_AAR_NATIVE_EVIDENCE_LINKED_NOT_RELEASE_CERTIFIED'
    assert result['elf_assessment_status'] == 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE'
    assert result['apk_packaging_verified'] is False


def test_reject_hash_and_path_mismatch_even_same_count():
    p, n = examples()
    bad = copy.deepcopy(n)
    bad['artifact_sha256'] = 'a' * 64
    assert status(p, bad).startswith('INCONCLUSIVE')
    bad = copy.deepcopy(n)
    bad['libraries'][1]['entry'] = 'jni/x86_64/libother.so'
    assert bridge.evaluate(p, bad)['reason'] == 'NATIVE_ENTRY_PATHS_MISMATCH'


def test_reject_unselected_and_incomplete_native():
    p, n = examples()
    p['status'] = 'NOT_SELECTED'
    assert status(p, n).startswith('INCONCLUSIVE')
    p, n = examples()
    n['status'] = n['alignment_summary']['status'] = 'UNKNOWN_64BIT_NATIVE_EVIDENCE'
    assert status(p, n).startswith('INCONCLUSIVE')
    p, n = examples()
    n['alignment_summary']['runtime_or_release_certified'] = True
    assert status(p, n).startswith('INCONCLUSIVE')


def test_reject_duplicates_and_scope_overclaim():
    p, n = examples()
    p['native_entry_paths'][1] = p['native_entry_paths'][0]
    assert status(p, n).startswith('INCONCLUSIVE')
    p, n = examples()
    n['libraries'][1]['entry'] = n['libraries'][0]['entry']
    assert status(p, n).startswith('INCONCLUSIVE')
    p, n = examples()
    p['actual_apk_packaging'] = 'VERIFIED'
    assert status(p, n).startswith('INCONCLUSIVE')


def test_utf16_probe_marker_and_cli(tmp_path):
    p, n = examples()
    log = tmp_path / 'positive.log'
    inspection = tmp_path / 'native.json'
    output = tmp_path / 'bridge.json'
    log.write_bytes(('other output\n' + bridge.MARKER + json.dumps(p) + '\n').encode('utf-16'))
    inspection.write_text(json.dumps(n), encoding='utf-8')
    assert bridge.main(['--probe-log', str(log), '--inspection-json', str(inspection), '--output', str(output)]) == 0
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'SCOPED_AAR_NATIVE_EVIDENCE_LINKED_NOT_RELEASE_CERTIFIED'


def test_duplicate_markers_and_missing_log(tmp_path):
    p, n = examples()
    log = tmp_path / 'dup.log'
    inspection = tmp_path / 'native.json'
    output = tmp_path / 'bridge.json'
    log.write_text(bridge.MARKER + json.dumps(p) + '\n' + bridge.MARKER + json.dumps(p) + '\n')
    inspection.write_text(json.dumps(n))
    assert bridge.main(['--probe-log', str(log), '--inspection-json', str(inspection), '--output', str(output)]) == 4
    assert not output.exists()


def test_reject_bad_schema():
    p, n = examples()
    p['schema_version'] = 'wrong'
    assert status(p, n).startswith('INCONCLUSIVE')


def test_reject_forged_elf_summary_and_abi_provenance():
    p, n = examples()
    n['status'] = n['alignment_summary']['status'] = 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE'
    assert bridge.evaluate(p, n)['reason'] == 'INSPECTOR_64BIT_SUMMARY_CONTRADICTION'
    p, n = examples()
    n['libraries'][0]['elf']['segments'][0]['aligned_16k'] = False
    assert bridge.evaluate(p, n)['reason'] == 'ELF_ALIGNMENT_FLAG_CONTRADICTION'
    p, n = examples()
    n['libraries'][0]['abi_from_archive_path'] = 'x86_64'
    assert bridge.evaluate(p, n)['reason'] == 'NATIVE_ABI_OR_SOURCE_ROLE_CONTRADICTION'
    p, n = examples()
    n['alignment_summary']['evaluated_64bit_elf_entries'] = 99
    assert bridge.evaluate(p, n)['reason'] == 'INSPECTOR_64BIT_ENTRY_COUNT_CONTRADICTION'
