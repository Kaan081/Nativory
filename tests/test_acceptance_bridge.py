"""Synthetic contract tests; real AAR proof comes from pinned GitHub runs."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools' / 'upgrade_workbench' / 'acceptance_bridge.py'
spec = importlib.util.spec_from_file_location('acceptance_bridge', MODULE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def elf(align: int) -> dict:
    return {'elf_class': 'ELF64', 'segments': [{'p_align': align, 'offset': 0, 'vaddr': 0, 'aligned_16k': align == 16384}]}


def report(version: str, align: int, checksum: str) -> dict:
    status = ('ATTENTION_64BIT_ALIGNMENT_EVIDENCE' if version == '0.6.0' else
              'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION')
    return {
        'artifact_format': 'aar', 'artifact_name': f'fbjni-{version}.aar',
        'artifact_sha256': checksum, 'native_library_count': 1,
        'status': status,
        'alignment_summary': {'status': status, 'runtime_or_release_certified': False},
        'libraries': [{'entry': 'jni/arm64-v8a/libfbjni.so',
                       'abi_from_archive_path': 'arm64-v8a', 'elf': elf(align)}],
    }


def create_case(root: Path) -> tuple[Path, Path]:
    app, pair = root / 'app', root / 'pair'
    app.mkdir(); pair.mkdir()
    (app / 'gradle-exit-code.txt').write_text('0\n')
    (app / 'dependency-insight.log').write_text('com.facebook.fbjni:fbjni:0.7.0\n'
                                                     'com.facebook.hermes:hermes-android:1.0\n'
                                                     'com.facebook.react:react-android:0.88.0\nBUILD SUCCESSFUL')
    log_record = {
        'scope': 'CI_GENERATED_EXPO58_APP_DEBUG_RUNTIME_ONLY',
        'status': 'SCOPED_APP_SELECTED_AAR_MATCH',
        'coordinate': bridge.EXPECTED,
        'sha256': 'b' * 64, 'reference_sha256': 'b' * 64,
        'artifact_bytes': 5, 'native_entry_count': 1,
        'native_entry_paths': ['jni/arm64-v8a/libfbjni.so'],
        'current_user_local_app_owner': 'NOT_VERIFIED',
        'apk_packaging_and_release': 'NOT_VERIFIED',
    }
    (app / 'app-selected-aar.log').write_text('RNWB_APP_AAR_PROVENANCE_V1:' + json.dumps(log_record) + '\nBUILD SUCCESSFUL')
    for version, align, hash_ in [('0.6.0', 4096, 'a' * 64), ('0.7.0', 16384, 'b' * 64)]:
        (pair / f'fbjni-{version}-workbench.json').write_text(json.dumps(report(version, align, hash_)))
        (pair / f'fbjni-{version}.aar.sha256').write_text(hash_)
    (pair / 'pair-result.json').write_text(json.dumps({
        'status': 'REAL_64BIT_ELF_NEGATIVE_POSITIVE_OBSERVED',
        '0.6.0': {'verified_64bit_entries': 1,
                  'independent_readelf': [{'entry': 'jni/arm64-v8a/libfbjni.so',
                                          'p_align': [4096], 'all_loads_16k': False}]},
        '0.7.0': {'verified_64bit_entries': 1,
                  'independent_readelf': [{'entry': 'jni/arm64-v8a/libfbjni.so',
                                          'p_align': [16384], 'all_loads_16k': True}]},
    }))
    return app, pair


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app, self.pair = create_case(Path(self.tmp.name))

    def test_scoped_success_never_app_fix(self):
        result = bridge.assess(self.app, self.pair)
        self.assertEqual(result['status'], bridge.POSITIVE)
        self.assertFalse(result['app_fix_accepted'])
        self.assertFalse(result['release_certified'])

    def test_missing_record_fails_closed(self):
        (self.app / 'app-selected-aar.log').unlink()
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_app_sha_mismatch_fails_closed(self):
        p = self.app / 'app-selected-aar.log'
        p.write_text(p.read_text().replace('b' * 64, 'c' * 64))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_readelf_disagreement_fails_closed(self):
        p = self.pair / 'pair-result.json'
        obj = json.loads(p.read_text())
        obj['0.7.0']['independent_readelf'][0]['p_align'] = [4096]
        p.write_text(json.dumps(obj))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_wrong_owner_fails_closed(self):
        p = self.app / 'dependency-insight.log'
        p.write_text(p.read_text().replace('com.facebook.hermes:hermes-android:', 'other:thing:'))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_fake_release_certification_fails_closed(self):
        p = self.pair / 'fbjni-0.7.0-workbench.json'
        obj = json.loads(p.read_text())
        obj['alignment_summary']['runtime_or_release_certified'] = True
        p.write_text(json.dumps(obj))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_no_positive_pair_fails_closed(self):
        p = self.pair / 'pair-result.json'
        obj = json.loads(p.read_text())
        obj['status'] = 'NO_VERIFIED_NEGATIVE_POSITIVE_PAIR'
        p.write_text(json.dumps(obj))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_duplicated_native_path_fails_closed(self):
        p = self.pair / 'fbjni-0.7.0-workbench.json'
        obj = json.loads(p.read_text())
        obj['libraries'].append(copy.deepcopy(obj['libraries'][0]))
        obj['native_library_count'] = 2
        p.write_text(json.dumps(obj))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_tampered_alignment_flag_fails_closed(self):
        p = self.pair / 'fbjni-0.7.0-workbench.json'
        obj = json.loads(p.read_text())
        obj['libraries'][0]['elf']['segments'][0]['p_align'] = 4096
        p.write_text(json.dumps(obj))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_missing_pt_load_offsets_fails_closed(self):
        p = self.pair / 'fbjni-0.7.0-workbench.json'
        obj = json.loads(p.read_text())
        del obj['libraries'][0]['elf']['segments'][0]['offset']
        p.write_text(json.dumps(obj))
        self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)

    def test_symlink_input_fails_closed(self):
        from unittest.mock import patch

        p = self.pair / 'pair-result.json'
        target = p.with_name('real.json')
        p.rename(target)
        try:
            p.symlink_to(target)
        except OSError as exc:
            if getattr(exc, 'winerror', None) != 1314:
                raise
            # Windows without symlink privilege: restore a valid input first,
            # then exercise the rejection path by simulating only is_symlink.
            target.rename(p)
            self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.POSITIVE)
            with patch.object(Path, 'is_symlink', autospec=True,
                              side_effect=lambda candidate: candidate == p):
                self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)
        else:
            self.assertEqual(bridge.assess(self.app, self.pair)['status'], bridge.UNKNOWN)


if __name__ == '__main__':
    unittest.main()
