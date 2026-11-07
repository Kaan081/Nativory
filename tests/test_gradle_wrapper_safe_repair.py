"""Offline synthetic tests; these never execute Gradle or edit a real app."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import pytest

FILE = Path(__file__).resolve().parents[1] / 'tools' / 'safe_repair' / 'gradle_wrapper_repair.py'
spec = importlib.util.spec_from_file_location('gradle_wrapper_repair_pilot', FILE)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def props(version='9.3.1', kind='bin', checksum=None, newline='\n'):
    lines = [
        'distributionBase=GRADLE_USER_HOME',
        f'distributionUrl=https\\://services.gradle.org/distributions/gradle-{version}-{kind}.zip',
    ]
    if checksum is not None:
        lines.append('distributionSha256Sum=' + checksum)
    lines += ['distributionPath=wrapper/dists', 'zipStoreBase=GRADLE_USER_HOME', 'zipStorePath=wrapper/dists']
    return (newline.join(lines) + newline).encode('utf-8')


def fixture_project(tmp_path, monkeypatch, before=None):
    target = tmp_path / 'android' / 'gradle' / 'wrapper' / 'gradle-wrapper.properties'
    target.parent.mkdir(parents=True)
    original = props() if before is None else before
    target.write_bytes(original)
    def fake_scan(_):
        raw = target.read_text()
        if 'gradle-9.3.1-' in raw:
            return '9.2.1', '9.3.1', 'blocked', '9.4.1'
        if 'gradle-9.4.1-' in raw:
            return '9.2.1', '9.4.1', 'checks_passed', '9.4.1'
        return None, None, 'unknown', None
    monkeypatch.setattr(repair, 'scan_project', fake_scan)
    return tmp_path, target


@pytest.mark.parametrize('kind', ['bin','all'])
def test_replacement_preserves_other_properties_adds_correct_checksum(kind):
    raw = props(kind=kind, newline='\r\n')
    new = repair.replacement(raw)
    assert f'gradle-9.4.1-{kind}.zip'.encode() in new
    assert f'distributionSha256Sum={repair.DISTRIBUTION_SHA256["9.4.1"][kind]}'.encode() in new
    assert b'\r\n' in new
    assert new.count(b'distributionPath=wrapper/dists') == 1
    assert b'\n' not in new.replace(b'\r\n', b'')


def test_upgrades_known_existing_checksum_and_preserves_unrelated_properties():
    raw = props(checksum=repair.DISTRIBUTION_SHA256['9.3.1']['bin'])
    new = repair.replacement(raw)
    assert b'distributionBase=GRADLE_USER_HOME' in new
    assert repair.DISTRIBUTION_SHA256['9.3.1']['bin'].encode() not in new
    assert repair.DISTRIBUTION_SHA256['9.4.1']['bin'].encode() in new


@pytest.mark.parametrize('raw', [
    props(checksum='0' * 64),
    props().replace(b'services.gradle.org', b'attacker.example'),
    props(version='9.2.1'),
    props() + b'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.3.1-bin.zip\n',
    props() + b'distributionSha256Sum=' + b'0'*64 + b'\n',
])
def test_unsupported_preimage_refused(raw):
    with pytest.raises(repair.RepairRefused):
        repair.replacement(raw)


def test_plan_ready_and_proposed_change(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    assert plan['status'] == 'READY_FOR_APPROVAL'
    assert plan['scanner_status'] == 'blocked'
    assert plan['before_sha256'] == repair.sha(target.read_bytes())
    assert '9.4.1' in plan['diff']
    assert plan['plan_id'] == repair.make_plan(project)['plan_id']


def test_plan_when_healthy_does_not_propose_edit(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch, props(version='9.4.1'))
    plan = repair.make_plan(project)
    assert plan['status'] == 'NO_REPAIR_NEEDED'
    assert plan['diff'] is None


def test_unresolved_scanner_must_not_propose_edit(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    monkeypatch.setattr(repair, 'scan_project', lambda _: (None, '9.3.1', 'unknown', None))
    assert repair.make_plan(project)['status'] == 'MANUAL_REVIEW_REQUIRED'
    assert target.read_bytes() == props()


def test_execute_verified_gradle_help_only(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    monkeypatch.setattr(repair, 'run_gradle_help', lambda _: (True, 0, 'BUILD SUCCESSFUL'))
    result = repair.execute(path, plan['plan_id'])
    assert result['status'] == 'VERIFIED_SCOPED_GRADLE_HELP_ONLY'
    assert repair.sha(target.read_bytes()) == plan['after_sha256']
    assert Path(result['original_backup_path']).read_bytes() == props()
    assert result['release_certified'] is False


def test_execute_rolls_back_failed_gradle_help(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    monkeypatch.setattr(repair, 'run_gradle_help', lambda _: (False, 1, 'injected failure'))
    result = repair.execute(path, plan['plan_id'])
    assert result['status'] == 'FAILED_AND_WRAPPER_ROLLED_BACK'
    assert target.read_bytes() == props()
    assert Path(result['original_backup_path']).read_bytes() == props()


def test_execute_rolls_back_scanner_not_passed(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    monkeypatch.setattr(repair, 'scan_project', lambda _: ('9.2.1','9.4.1','unknown','9.4.1'))
    with pytest.raises(repair.RepairRefused, match='STALE'):
        repair.execute(path, plan['plan_id'])
    assert target.read_bytes() == props()


def test_stale_input_aborts_without_modifying_file(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    target.write_bytes(target.read_bytes() + b'# changed after plan\n')
    with pytest.raises(repair.RepairRefused, match='STALE'):
        repair.execute(path, plan['plan_id'])
    assert target.read_bytes().endswith(b'# changed after plan\n')


def test_missing_explicit_approval_refused(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    with pytest.raises(repair.RepairRefused, match='APPROVAL'):
        repair.execute(path, '0' * 64)
    assert target.read_bytes() == props()


def test_modifying_plan_payload_invalidates_id(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    plan['after_sha256'] = 'f' * 64
    path.write_text(json.dumps(plan))
    with pytest.raises(repair.RepairRefused, match='TAMPERED'):
        repair.execute(path, plan['plan_id'])
    assert target.read_bytes() == props()


def test_preexisting_backup_refused_without_modification(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    backup = path.with_name(path.name + '.' + plan['plan_id'][:12] + '.original.bak')
    backup.write_bytes(b'do not overwrite')
    with pytest.raises(repair.RepairRefused, match='BACKUP_ALREADY_EXISTS'):
        repair.execute(path, plan['plan_id'])
    assert backup.read_bytes() == b'do not overwrite'
    assert target.read_bytes() == props()


def test_symlink_wrapper_refused(tmp_path):
    d = tmp_path / 'android' / 'gradle' / 'wrapper'
    d.mkdir(parents=True)
    actual = tmp_path / 'real.properties'
    actual.write_bytes(props())
    symlink = d / 'gradle-wrapper.properties'
    try:
        symlink.symlink_to(actual)
    except (OSError, NotImplementedError):
        pytest.skip('symlink privileges unavailable on Windows')
    with pytest.raises(repair.RepairRefused, match='SYMLINK'):
        repair.wrapper_path(tmp_path)


def test_atomic_execute_never_overwrites_concurrent_change(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    def simulate_external_change(_):
        target.write_bytes(b'another actor changed file\n')
        return False, 1, 'simulated'
    monkeypatch.setattr(repair, 'run_gradle_help', simulate_external_change)
    result = repair.execute(path, plan['plan_id'])
    assert result['status'] == 'MANUAL_RECOVERY_REQUIRED_WRAPPER_CHANGED'
    assert target.read_bytes() == b'another actor changed file\n'


def test_duplicate_output_guard(tmp_path):
    path = tmp_path / 'existing.json'
    path.write_text('original')
    with pytest.raises(repair.RepairRefused, match='OUTPUT_ALREADY_EXISTS'):
        repair.store_json_exclusive(path, {'a': 1})
    assert path.read_text() == 'original'


def test_postwrite_scanner_unknown_causes_rollback(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    def scanner_after_write(_):
        if b'gradle-9.4.1-' in target.read_bytes():
            return '9.2.1', None, 'unknown', None
        return '9.2.1', '9.3.1', 'blocked', '9.4.1'
    monkeypatch.setattr(repair, 'scan_project', scanner_after_write)
    monkeypatch.setattr(repair, 'run_gradle_help', lambda _: pytest.fail('Should not run Gradle'))
    result = repair.execute(path, plan['plan_id'])
    assert result['status'] == 'FAILED_AND_WRAPPER_ROLLED_BACK'
    assert result['reason'] == 'SCANNER_DID_NOT_CONFIRM_FIX'
    assert target.read_bytes() == props()


def test_unexpected_gradle_exception_causes_rollback(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    path = tmp_path / 'repair-plan.json'
    repair.store_json_exclusive(path, plan)
    def crash(_):
        raise RuntimeError('Simulated')
    monkeypatch.setattr(repair, 'run_gradle_help', crash)
    result = repair.execute(path, plan['plan_id'])
    assert result['status'] == 'FAILED_AND_WRAPPER_ROLLED_BACK'
    assert result['reason'] == 'UNEXPECTED_VERIFICATION_ERROR_RuntimeError'
    assert target.read_bytes() == props()

# v0.2: observable, explicitly approved recovery from a persisted v0.1 backup.

def interrupted_repair(tmp_path, monkeypatch):
    project, target = fixture_project(tmp_path, monkeypatch)
    plan = repair.make_plan(project)
    plan_path = project / 'repair-plan.json'
    repair.store_json_exclusive(plan_path, plan)
    original = target.read_bytes()
    backup = plan_path.with_name(plan_path.name + '.' + plan['plan_id'][:12] + '.original.bak')
    backup.write_bytes(original)
    target.write_bytes(repair.replacement(original))
    return plan, plan_path, target, backup, original


def test_recovery_preview_does_not_write(tmp_path, monkeypatch):
    plan, plan_path, target, _, original = interrupted_repair(tmp_path, monkeypatch)
    after = target.read_bytes()
    report = repair.recover(plan_path, plan['plan_id'])
    assert report['status'] == 'RESTORABLE_WRAPPER_AFTER_IMAGE'
    assert report['restore_requested'] is False
    assert report['gradle_or_build_verified'] is False
    assert target.read_bytes() == after != original


def test_recovery_explicit_restore_exact_bytes(tmp_path, monkeypatch):
    plan, plan_path, target, _, original = interrupted_repair(tmp_path, monkeypatch)
    report = repair.recover(plan_path, plan['plan_id'], restore=True)
    assert report['status'] == 'WRAPPER_RESTORED_FROM_BACKUP'
    assert target.read_bytes() == original
    second = repair.recover(plan_path, plan['plan_id'], restore=True)
    assert second['status'] == 'ORIGINAL_ALREADY_PRESENT'


def test_recovery_does_not_overwrite_external_change(tmp_path, monkeypatch):
    plan, plan_path, target, _, _ = interrupted_repair(tmp_path, monkeypatch)
    target.write_bytes(b'external change\n')
    report = repair.recover(plan_path, plan['plan_id'], restore=True)
    assert report['status'] == 'MANUAL_RECOVERY_REQUIRED_WRAPPER_CHANGED'
    assert target.read_bytes() == b'external change\n'


def test_recovery_bad_backup_refused_without_write(tmp_path, monkeypatch):
    plan, plan_path, target, backup, _ = interrupted_repair(tmp_path, monkeypatch)
    post = target.read_bytes()
    backup.write_bytes(b'not the saved preimage')
    report = repair.recover(plan_path, plan['plan_id'], restore=True)
    assert report['status'] == 'MANUAL_RECOVERY_REQUIRED_BACKUP_INVALID'
    assert target.read_bytes() == post


def test_recovery_missing_backup_refused_without_write(tmp_path, monkeypatch):
    plan, plan_path, target, backup, _ = interrupted_repair(tmp_path, monkeypatch)
    post = target.read_bytes()
    backup.unlink()
    report = repair.recover(plan_path, plan['plan_id'], restore=True)
    assert report['status'] == 'MANUAL_RECOVERY_REQUIRED_BACKUP_INVALID'
    assert target.read_bytes() == post


def test_recovery_wrong_approval_and_tampered_plan_refused(tmp_path, monkeypatch):
    plan, plan_path, target, _, _ = interrupted_repair(tmp_path, monkeypatch)
    post = target.read_bytes()
    with pytest.raises(repair.RepairRefused, match='APPROVAL_TOKEN'):
        repair.recover(plan_path, 'f' * 64, restore=True)
    plan['before_sha256'] = '0' * 64
    plan_path.write_text(json.dumps(plan))
    with pytest.raises(repair.RepairRefused, match='TAMPERED'):
        repair.recover(plan_path, plan['plan_id'], restore=True)
    assert target.read_bytes() == post


def test_recovery_cli_preview_and_explicit_trust_gate(tmp_path, monkeypatch):
    plan, plan_path, target, _, original = interrupted_repair(tmp_path, monkeypatch)
    preview = tmp_path / 'preview.json'
    assert repair.main(['recover', '--plan', str(plan_path), '--approve', plan['plan_id'],
                        '--report', str(preview)]) == 0
    assert json.loads(preview.read_text())['status'] == 'RESTORABLE_WRAPPER_AFTER_IMAGE'
    assert target.read_bytes() != original
    no_trust = tmp_path / 'no-trust.json'
    assert repair.main(['recover', '--plan', str(plan_path), '--approve', plan['plan_id'],
                        '--restore', '--report', str(no_trust)]) == 4
    assert not no_trust.exists()
    assert target.read_bytes() != original
    final = tmp_path / 'restored.json'
    assert repair.main(['recover', '--plan', str(plan_path), '--approve', plan['plan_id'],
                        '--restore', '--trust-disposable-project', '--report', str(final)]) == 0
    assert json.loads(final.read_text())['status'] == 'WRAPPER_RESTORED_FROM_BACKUP'
    assert target.read_bytes() == original


def test_cooperating_second_repair_lock_is_refused(tmp_path):
    with repair.project_repair_lock(tmp_path):
        with pytest.raises(repair.RepairRefused, match='REPAIR_ALREADY_RUNNING'):
            with repair.project_repair_lock(tmp_path):
                pytest.fail('Second lock should not be acquired')
    with repair.project_repair_lock(tmp_path):
        pass  # Lock released cleanly.


def test_recovery_empty_backup_is_manual_only(tmp_path, monkeypatch):
    plan, plan_path, target, backup, _ = interrupted_repair(tmp_path, monkeypatch)
    post = target.read_bytes()
    backup.write_bytes(b'')
    report = repair.recover(plan_path, plan['plan_id'], restore=True)
    assert report['status'] == 'MANUAL_RECOVERY_REQUIRED_BACKUP_INVALID'
    assert report['reason'] == 'BACKUP_UNREADABLE'
    assert target.read_bytes() == post
