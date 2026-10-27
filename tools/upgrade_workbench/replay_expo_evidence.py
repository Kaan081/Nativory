"""Replay previously captured Expo #50293 isolated Gradle evidence without reruns.

This checks self-consistency of supplied records and saved logs, NOT that logs are
trusted remote attestations or that the current application works.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

EXPECTED_CASES = [
    ('A_old_plugin_kotlin_2_2_10', '2.2.10', True, False, True),
    ('B_old_plugin_kotlin_2_3_20', '2.3.20', True, True, False),
    ('C_kotlin_2_3_20_no_expo_plugin', '2.3.20', False, False, True),
]
ARTIFACT = 'io.github.expo:expo-modules-v2-compiler-plugin:0.2.0-2.3.20'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def recorded_text_hash_match(raw: bytes, recorded: object) -> tuple[bool, str]:
    """Check a historic text hash written before Windows newline conversion.

    Older capture script hashed the in-memory UTF-8 string before calling
    Path.write_text; on Windows that write may translate LF to CRLF.
    Raw bytes take precedence. The only accepted fallback is CRLF -> LF;
    any substantive content alteration remains a mismatch. This does NOT
    authenticate who generated the evidence or attest original raw bytes.
    """
    if not isinstance(recorded, str) or len(recorded) != 64:
        return False, 'INVALID_RECORDED_DIGEST'
    if sha(raw) == recorded:
        return True, 'RAW_BYTES'
    if b'\r\n' in raw and sha(raw.replace(b'\r\n', b'\n')) == recorded:
        return True, 'WINDOWS_CRLF_TO_LF_TEXT_EQUIVALENCE'
    return False, 'MISMATCH'


def read_json(folder: Path) -> dict:
    path = folder / 'result.json'
    if not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError('MISSING_OR_OVERSIZE_RESULT_JSON')
    return json.loads(path.read_text(encoding='utf-8'))


def read_log(folder: Path, name: str) -> tuple[str, str]:
    if '/' in name or '\\' in name or name.startswith('.') or not name.endswith('.log'):
        raise ValueError('INVALID_LOG_NAME')
    path = folder / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_000_000:
        raise ValueError('MISSING_UNSUPPORTED_OR_OVERSIZE_LOG')
    raw = path.read_bytes()
    return raw.decode('utf-8', errors='replace'), sha(raw)


def evaluate(old_dir: Path, fixed_dir: Path) -> dict:
    if old_dir.is_symlink() or fixed_dir.is_symlink():
        raise ValueError('SYMLINK_EVIDENCE_FOLDER')
    old, fixed = read_json(old_dir), read_json(fixed_dir)
    checks = {}
    checks['old_experiment_identity'] = (
        old.get('experiment') == 'EXPO-KOTLIN-PREFLIGHT-01-GRADLE'
        and old.get('gradle') == '8.14'
        and old.get('expo_compiler_plugin') == '0.1.5'
        and old.get('repo_clean_unchanged') is True
        and all(isinstance(old.get(key), str) and len(old[key]) == 64 for key in
                ('gradle_sha256', 'expo_plugin_jar_sha256'))
    )
    old_arms = old.get('arms') if isinstance(old.get('arms'), list) else []
    hashes = {}
    for case, kgp, plugin, has_failure, expected_success in EXPECTED_CASES:
        rows = [r for r in old_arms if isinstance(r, dict) and r.get('case') == case]
        valid = len(rows) == 1
        if valid:
            row = rows[0]
            if row.get('log_file') != case + '.log':
                valid = False
            else:
                log, h = read_log(old_dir, case + '.log')
                hashes[case] = h
                exact = ('AbstractMethodError' in log and 'getPluginId' in log and
                         ('ExpoModulesV2' in log or 'io.github.expo.modules.v2.compiler' in log))
                code = row.get('exit_code')
                valid = (
                    row.get('kgp_declared') == kgp
                    and row.get('expo_compiler_plugin_enabled') is plugin
                    and row.get('timed_out') is False
                    and row.get('exact_upstream_error') is exact
                    and exact is has_failure
                    and (code == 0 if expected_success else isinstance(code, int) and code != 0)
                )
        checks['old_' + case] = valid
    checks['three_old_arms_only'] = len(old_arms) == 3
    # On Windows the original result status may be SETUP_OR_RUN_ERROR because
    # Gradle file handles stayed locked at cleanup. This does not invalidate
    # saved compile logs, but the discrepancy must remain visible.
    checks['old_status_explained'] = (
        old.get('status') == 'PASS_RUNTIME_REGRESSION_ISOLATED'
        or (old.get('status') == 'SETUP_OR_RUN_ERROR' and 'WinError 32' in str(old.get('error', '')))
    )
    fixed_log, fixed_sha = read_log(fixed_dir, 'fixed_arm.log')
    hashes['fixed_arm'] = fixed_sha
    fixed_artifacts = fixed.get('observed_compiler_plugin_artifacts', [])
    checks['fixed_identity'] = (
        fixed.get('experiment') == 'EXPO-KOTLIN-PREFLIGHT-01-FIXED-ARM'
        and fixed.get('kotlin_gradle_plugin') == '2.3.20'
        and fixed.get('expo_v2_gradle_plugin') == '0.2.0'
        and fixed.get('repo_clean_unchanged') is True
    )
    checks['fixed_run'] = (
        fixed.get('status') == 'PASS_FIXED_PLUGIN_REAL_GRADLE_COMPILE'
        and fixed.get('exit_code') == 0
        and fixed.get('timed_out') is False
        and fixed.get('expo_gradle_plugin_applied') is True
        and 'RN_EVIDENCE_EXPO_APPLIED=true' in fixed_log
        and not ('AbstractMethodError' in fixed_log and 'getPluginId' in fixed_log)
    )
    checks['fixed_artifact_in_gradle_log'] = (
        isinstance(fixed_artifacts, list) and ARTIFACT in fixed_artifacts
        and ('RN_EVIDENCE_ARTIFACT=' + ARTIFACT) in fixed_log
    )
    log_ok, log_mode = recorded_text_hash_match((fixed_dir / 'fixed_arm.log').read_bytes(), fixed.get('log_sha256'))
    checks['fixed_log_hash_matches_recorded'] = log_ok
    build_path = fixed_dir / 'build.gradle.kts'
    source_ok, source_mode = False, 'MISSING_OR_UNSUPPORTED'
    if (build_path.is_file() and not build_path.is_symlink()
            and build_path.stat().st_size < 3_000_000):
        source_ok, source_mode = recorded_text_hash_match(
            build_path.read_bytes(), fixed.get('build_gradle_sha256'))
    checks['fixed_source_hash_matches_recorded'] = source_ok
    outcome = 'REPLAYED_HISTORICAL_EVIDENCE_CONSISTENT' if all(checks.values()) else 'INCONCLUSIVE_EVIDENCE_MISMATCH'
    return {
        'schema_version': 'rn-upgrade-workbench-evidence-replay-0.1',
        'case_id': 'EXPO-50293-ISOLATED-EVIDENCE-REPLAY',
        'status': outcome,
        'checks': checks,
        'evidence_sha256': hashes,
        'fixed_text_hash_comparison': {
            'log': log_mode,
            'build_gradle': source_mode,
        },
        'original_harness_status': old.get('status'),
        'fixed_harness_status': fixed.get('status'),
        'scope': 'SAVED_LOCAL_GRADLE_EVIDENCE_CONSISTENCY_ONLY',
        'not_verified': [
            'Independent or tamper-proof capture of historical runs',
            'Current Expo Android app builds successfully',
            'All compiler runtime, APK, device or Play release tests',
            'Senior engineer time saved or paid product adoption',
            'Raw-byte hash attestation for historical fixed text files when CRLF normalization was required',
        ],
    }
