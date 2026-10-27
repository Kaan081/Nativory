"""Targeted regressions for PR #1 hardening; no network or Gradle."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

WB = Path(__file__).resolve().parents[1] / 'tools' / 'upgrade_workbench'
sys.path.insert(0, str(WB))
from inspect_native_artifact import inspect
import inspect_native_artifact
from workbench import summarize_log, verify


def test_streamed_log_digest_and_oversize(tmp_path):
    content = b'a' * (8 * 1024 * 1024 + 37)
    log = tmp_path / 'large.log'
    log.write_bytes(content)
    sha, size, oversized, prefix = summarize_log(log)
    assert sha == hashlib.sha256(content).hexdigest()
    assert size == len(content)
    assert oversized is True
    assert len(prefix) == 8 * 1024 * 1024


def test_total_native_payload_budget_before_inflate(tmp_path, monkeypatch):
    artifact = tmp_path / 'native.aar'
    with zipfile.ZipFile(artifact, 'w') as archive:
        archive.writestr('jni/arm64-v8a/libprobe.so', b'x' * 64,
                         compress_type=zipfile.ZIP_DEFLATED)
    monkeypatch.setattr(inspect_native_artifact, 'MAX_TOTAL_SO_BYTES', 63)
    with pytest.raises(ValueError, match='TOTAL_NATIVE_PAYLOAD_BUDGET_EXCEEDED'):
        inspect(artifact)


def manifest_for(before_cwd, after_cwd):
    return {
        'schema_version': 'rn-upgrade-case-0.1',
        'case_id': 'BEFORE_PRECONDITION_GATE',
        'scope': 'user_defined_command',
        'failure_marker': 'EXPECTED_FAILURE',
        'after_artifact_marker': 'EXPECTED_AFTER_MARKER',
        'runs': {
            'before': {
                'cwd': before_cwd,
                'argv': [sys.executable, '-c',
                         'print("UNRELATED_FAILURE"); raise SystemExit(1)'],
            },
            'after': {
                'cwd': after_cwd,
                'argv': [sys.executable, '-c',
                         'from pathlib import Path; Path("after-was-run").write_text("bad")'],
            },
        },
    }


def test_before_failure_does_not_execute_after(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'before').mkdir(parents=True)
    (ws / 'after').mkdir()
    manifest = tmp_path / 'case.json'
    manifest.write_text(json.dumps(manifest_for('before', 'after')))
    report = verify(manifest, ws, tmp_path / 'result', 10, execute=True)
    assert report['status'] == 'UNKNOWN_BEFORE_DIFFERENT_FAILURE'
    assert report['runs']['after']['skipped_due_to_before_precondition'] is True
    assert not (ws / 'after' / 'after-was-run').exists()
    assert 'AFTER_NOT_EXECUTED_BEFORE_PRECONDITION_FAILED' in report['observations']


def test_nested_before_after_rejected(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'before' / 'after').mkdir(parents=True)
    manifest = tmp_path / 'case.json'
    manifest.write_text(json.dumps(manifest_for('before', 'before/after')))
    with pytest.raises(ValueError, match='BEFORE_AFTER_WORKSPACES_OVERLAP'):
        verify(manifest, ws, tmp_path / 'result', 10, execute=True)
    assert not (tmp_path / 'result').exists()
