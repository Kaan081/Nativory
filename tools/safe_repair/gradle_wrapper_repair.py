#!/usr/bin/env python3
"""Experimental, narrowly scoped Gradle-wrapper repair transaction for trusted lab apps.

Only AGP 9.2.1 + Gradle 9.3.1 -> Gradle 9.4.1 (-bin or -all) is supported.
This does NOT certify builds, APKs, 16KiB alignment, production release, or safety of Gradle code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import difflib
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

SCHEMA = 'nativory-gradle-wrapper-repair-0.1'
RELATIVE_WRAPPER = Path('android/gradle/wrapper/gradle-wrapper.properties')
OLD_VERSION = '9.3.1'
NEW_VERSION = '9.4.1'
AGP_VERSION = '9.2.1'
# Offline pinned sums from https://gradle.org/release-checksums/ (2026-11-07).
DISTRIBUTION_SHA256 = {
    '9.3.1': {
        'bin': 'b266d5ff6b90eada6dc3b20cb090e3731302e553a27c5d3e4df1f0d76beaff06',
        'all': '17f277867f6914d61b1aa02efab1ba7bb439ad652ca485cd8ca6842fccec6e43',
    },
    '9.4.1': {
        'bin': '2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb',
        'all': '708d2c6ecc97ca9a11838ef64a6c2301151b8dd10387e22dc1a12c30557cab5b',
    },
}
KEY = re.compile(r'^\s*(distributionUrl|distributionSha256Sum)\s*=\s*(.*?)\s*$')
URL = re.compile(r'^(https(?:\\:|:)//services\.gradle\.org/distributions/gradle-)9\.3\.1-(bin|all)\.zip$')
HEX = re.compile(r'^[0-9a-f]{64}$')
MAX_PROPERTIES = 16 * 1024


class RepairRefused(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scan_project(project: Path) -> tuple[str | None, str | None, str, str | None]:
    """Use the existing static scanner as the sole source of resolved AGP/Gradle facts."""
    from rn_readiness.cli import run
    analysis = run(str(project))
    return (analysis.agp.value if analysis.agp.is_resolved else None,
            analysis.gradle.value if analysis.gradle.is_resolved else None,
            analysis.status.value,
            analysis.finding.required_gradle)


def wrapper_path(project: Path) -> Path:
    project = project.expanduser().absolute()
    if not project.is_dir() or project.is_symlink():
        raise RepairRefused('PROJECT_NOT_DIRECTORY_OR_SYMLINK')
    candidate = project
    for part in RELATIVE_WRAPPER.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise RepairRefused('WRAPPER_PATH_CONTAINS_SYMLINK')
    if not candidate.is_file():
        raise RepairRefused('WRAPPER_PROPERTIES_NOT_FOUND')
    return candidate


def read_wrapper(path: Path) -> bytes:
    if path.is_symlink():
        raise RepairRefused('WRAPPER_PATH_IS_SYMLINK')
    if path.stat().st_size > MAX_PROPERTIES:
        raise RepairRefused('WRAPPER_PROPERTIES_TOO_LARGE')
    raw = path.read_bytes()
    if not raw or b'\x00' in raw:
        raise RepairRefused('EMPTY_OR_BINARY_WRAPPER')
    try:
        raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise RepairRefused('WRAPPER_NOT_UTF8') from exc
    if b'\r' in raw.replace(b'\r\n', b''):
        raise RepairRefused('UNSUPPORTED_LINE_ENDINGS')
    return raw


def replacement(before: bytes) -> bytes:
    text = before.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines(keepends=True)
    fields: dict[str, tuple[int, str]] = {}
    for i, original in enumerate(lines):
        match = KEY.fullmatch(original.rstrip('\r\n'))
        if match:
            name, value = match.groups()
            if name in fields:
                raise RepairRefused('DUPLICATE_WRAPPER_KEY_' + name)
            fields[name] = (i, value)
    if 'distributionUrl' not in fields:
        raise RepairRefused('DISTRIBUTION_URL_MISSING')
    url_index, value = fields['distributionUrl']
    match = URL.fullmatch(value)
    if match is None:
        raise RepairRefused('UNSUPPORTED_DISTRIBUTION_URL_OR_VERSION')
    kind = match.group(2)
    old_sum = DISTRIBUTION_SHA256[OLD_VERSION][kind]
    new_sum = DISTRIBUTION_SHA256[NEW_VERSION][kind]
    if 'distributionSha256Sum' in fields:
        _, checksum = fields['distributionSha256Sum']
        if checksum != old_sum:
            raise RepairRefused('OLD_DISTRIBUTION_CHECKSUM_UNRECOGNIZED')
    new_url = f'{match.group(1)}{NEW_VERSION}-{kind}.zip'
    lines[url_index] = lines[url_index].replace(value, new_url, 1)
    if 'distributionSha256Sum' in fields:
        sum_index, _ = fields['distributionSha256Sum']
        lines[sum_index] = f'distributionSha256Sum={new_sum}' + (
            newline if lines[sum_index].endswith(('\r\n', '\n')) else '')
    else:
        # Preserve existing keys; add the official new distribution checksum adjacent to URL.
        if not lines[url_index].endswith(('\r\n', '\n')):
            lines[url_index] += newline
        lines.insert(url_index + 1, f'distributionSha256Sum={new_sum}{newline}')
    return ''.join(lines).encode('utf-8')


def make_plan(project: Path) -> dict:
    project = project.expanduser().absolute()
    path = wrapper_path(project)
    before = read_wrapper(path)
    agp, gradle, check, required = scan_project(project)
    base = {
        'schema_version': SCHEMA,
        'status': 'MANUAL_REVIEW_REQUIRED',
        'reason': 'UNSUPPORTED_OR_UNRESOLVED_FACTS',
        'project_root': str(project),
        'relative_wrapper_path': RELATIVE_WRAPPER.as_posix(),
        'agp': agp,
        'gradle': gradle,
        'required_gradle': required,
        'scanner_status': check,
        'before_sha256': sha(before),
        'after_sha256': None,
        'diff': None,
    }
    if agp == AGP_VERSION and gradle == NEW_VERSION and check == 'checks_passed':
        base['status'] = 'NO_REPAIR_NEEDED'
        base['reason'] = 'WRAPPER_ALREADY_COMPATIBLE'
    elif agp == AGP_VERSION and gradle == OLD_VERSION and check == 'blocked' and required == NEW_VERSION:
        try:
            after = replacement(before)
        except RepairRefused as exc:
            base['reason'] = str(exc)
        else:
            base.update({
                'status': 'READY_FOR_APPROVAL',
                'reason': 'EXACT_AGP_GRADLE_MISMATCH_AND_PINNED_REPAIR',
                'after_sha256': sha(after),
                'diff': ''.join(difflib.unified_diff(
                    before.decode().splitlines(keepends=True),
                    after.decode().splitlines(keepends=True),
                    fromfile='a/' + RELATIVE_WRAPPER.as_posix(),
                    tofile='b/' + RELATIVE_WRAPPER.as_posix())),
            })
    base['plan_id'] = sha(json.dumps(base, sort_keys=True, ensure_ascii=True).encode('utf-8'))
    return base


def store_json_exclusive(path: Path, data: dict) -> None:
    if path.is_symlink() or path.exists():
        raise RepairRefused('OUTPUT_ALREADY_EXISTS')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as out:
        json.dump(data, out, indent=2, sort_keys=True)
        out.write('\n')


def read_plan(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise RepairRefused('PLAN_MISSING_OR_INVALID')
    try:
        value = json.loads(path.read_text('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RepairRefused('PLAN_INVALID_JSON') from exc
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA:
        raise RepairRefused('PLAN_SCHEMA_MISMATCH')
    return value


def atomic_replace(path: Path, content: bytes) -> None:
    # Atomic single-file replacement (not a repository-wide transaction).
    fd, temp = tempfile.mkstemp(prefix='.nativory-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, path.stat().st_mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run_gradle_help(project: Path) -> tuple[bool, int | None, str]:
    command = project / 'android' / ('gradlew.bat' if os.name == 'nt' else 'gradlew')
    if command.is_symlink() or not command.is_file():
        return (False, None, 'TRUSTED_GRADLE_WRAPPER_EXECUTABLE_MISSING')
    try:
        completed = subprocess.run(
            [str(command), 'help', '--no-daemon', '--console=plain'],
            cwd=project / 'android', capture_output=True, text=True,
            errors='replace', timeout=240, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, None, f'GRADLE_EXECUTION_ERROR:{type(exc).__name__}')
    output = (completed.stdout + '\n' + completed.stderr)[-12000:]
    return (completed.returncode == 0, completed.returncode, output)


@contextmanager
def project_repair_lock(project: Path):
    """Best-effort cross-process exclusion among cooperating Nativory repair commands.

    Lock file lives outside the project and is deliberately retained, so we do
    not create an unlink/recreate race. This does not lock non-Nativory editors.
    """
    project = project.expanduser().resolve(strict=True)
    lock_dir = Path(tempfile.gettempdir()) / 'nativory-wrapper-repair-locks'
    if lock_dir.is_symlink():
        raise RepairRefused('REPAIR_LOCK_DIRECTORY_SYMLINK')
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = lock_dir / (sha(os.fsencode(str(project))) + '.lock')
    if lock_path.is_symlink():
        raise RepairRefused('REPAIR_LOCK_SYMLINK')
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(lock_path, flags, 0o600)
    acquired = False
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                # msvcrt.locking locks a byte range from the current file offset.
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b'0')
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (OSError, PermissionError) as exc:
            raise RepairRefused('REPAIR_ALREADY_RUNNING_OR_LOCK_UNAVAILABLE') from exc
        yield
    finally:
        try:
            if acquired:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def approved_plan(plan_path: Path, approval_id: str) -> dict:
    plan = read_plan(plan_path)
    if plan.get('status') != 'READY_FOR_APPROVAL' or not HEX.fullmatch(approval_id):
        raise RepairRefused('PLAN_NOT_APPROVABLE')
    if plan.get('plan_id') != approval_id:
        raise RepairRefused('PLAN_APPROVAL_TOKEN_MISMATCH')
    payload = dict(plan)
    payload.pop('plan_id', None)
    if sha(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()) != approval_id:
        raise RepairRefused('PLAN_CONTENT_TAMPERED')
    return plan


def recover(plan_path: Path, approval_id: str, *, restore: bool = False) -> dict:
    """Inspect or explicitly restore the original wrapper after an interrupted repair.

    Accepts only exact original/after bytes described by the approved plan. It
    never runs Gradle and never rewrites an unexpected third-party change.
    """
    plan = approved_plan(plan_path, approval_id)
    project = Path(plan['project_root'])
    with project_repair_lock(project):
        target = wrapper_path(project)
        backup = plan_path.with_name(plan_path.name + '.' + approval_id[:12] + '.original.bak')
        report = {
            'schema_version': SCHEMA,
            'status': 'MANUAL_RECOVERY_REQUIRED_BACKUP_INVALID',
            'plan_id': approval_id,
            'project_root': str(project),
            'wrapper_path': str(target),
            'original_backup_path': str(backup),
            'original_sha256': plan['before_sha256'],
            'new_sha256': plan['after_sha256'],
            'restore_requested': restore,
            'gradle_or_build_verified': False,
            'reason': None,
        }
        if not isinstance(plan.get('before_sha256'), str) or not HEX.fullmatch(plan['before_sha256']) or \
                not isinstance(plan.get('after_sha256'), str) or not HEX.fullmatch(plan['after_sha256']):
            raise RepairRefused('PLAN_HASHES_INVALID')
        if backup.is_symlink() or not backup.is_file() or backup.stat().st_size > MAX_PROPERTIES:
            report['reason'] = 'BACKUP_MISSING_UNSAFE_OR_TOO_LARGE'
            return report
        try:
            original = read_wrapper(backup)
        except (RepairRefused, OSError):
            report['reason'] = 'BACKUP_UNREADABLE'
            return report
        if sha(original) != plan['before_sha256']:
            report['reason'] = 'BACKUP_SHA256_MISMATCH'
            return report
        current = read_wrapper(target)
        current_sha = sha(current)
        report['current_sha256'] = current_sha
        if current_sha == plan['before_sha256']:
            report.update(status='ORIGINAL_ALREADY_PRESENT', reason='NO_RESTORE_NEEDED')
        elif current_sha != plan['after_sha256']:
            report.update(status='MANUAL_RECOVERY_REQUIRED_WRAPPER_CHANGED', reason='TARGET_NOT_APPROVED_POSTIMAGE')
        elif not restore:
            report.update(status='RESTORABLE_WRAPPER_AFTER_IMAGE', reason='EXPLICIT_RESTORE_REQUIRED')
        else:
            # Cooperative lock is held; a noncooperating process can still race.
            if sha(read_wrapper(target)) != plan['after_sha256']:
                report.update(status='MANUAL_RECOVERY_REQUIRED_WRAPPER_CHANGED', reason='TARGET_CHANGED_BEFORE_RESTORE')
            else:
                atomic_replace(target, original)
                if sha(read_wrapper(target)) != plan['before_sha256']:
                    report.update(status='MANUAL_RECOVERY_REQUIRED_ROLLBACK_ERROR', reason='POST_RESTORE_HASH_MISMATCH')
                else:
                    report.update(status='WRAPPER_RESTORED_FROM_BACKUP', reason='ORIGINAL_BYTES_RESTORED')
        return report


def execute(plan_path: Path, approval_id: str) -> dict:
    plan = approved_plan(plan_path, approval_id)
    project = Path(plan['project_root'])
    with project_repair_lock(project):
        return _execute_under_lock(plan_path, approval_id, plan, project)


def _execute_under_lock(plan_path: Path, approval_id: str, plan: dict, project: Path) -> dict:
    current = make_plan(project)
    if current != plan:
        raise RepairRefused('PLAN_STALE_OR_PROJECT_CHANGED')
    path = wrapper_path(project)
    before = read_wrapper(path)
    after = replacement(before)
    if sha(before) != plan['before_sha256'] or sha(after) != plan['after_sha256']:
        raise RepairRefused('WRAPPER_PREIMAGE_OR_POSTIMAGE_MISMATCH')
    backup = plan_path.with_name(plan_path.name + '.' + approval_id[:12] + '.original.bak')
    if backup.exists() or backup.is_symlink():
        raise RepairRefused('BACKUP_ALREADY_EXISTS')
    # Backup is made BEFORE touching the target. A persistent file supports recovery on crash.
    with backup.open('xb') as stream:
        stream.write(before)
        stream.flush()
        os.fsync(stream.fileno())
    report = {
        'schema_version': SCHEMA,
        'status': 'INCOMPLETE',
        'reason': None,
        'plan_id': approval_id,
        'project_root': str(project),
        'wrapper_path': str(path),
        'original_sha256': sha(before),
        'new_sha256': sha(after),
        'original_backup_path': str(backup),
        'gradle_help_exit': None,
        'gradle_help_log_tail': None,
        'release_certified': False,
    }
    # Only a trusted disposable lab app should reach this point; Gradle runs arbitrary build logic.
    try:
        if sha(read_wrapper(path)) != sha(before):
            raise RepairRefused('WRAPPER_CHANGED_BEFORE_APPLY')
        atomic_replace(path, after)
        if sha(read_wrapper(path)) != sha(after):
            raise RepairRefused('POSTWRITE_HASH_MISMATCH')
        agp, gradle, state, required = scan_project(project)
        if (agp, gradle, state) != (AGP_VERSION, NEW_VERSION, 'checks_passed'):
            raise RepairRefused('SCANNER_DID_NOT_CONFIRM_FIX')
        ok, exit_code, log = run_gradle_help(project)
        report['gradle_help_exit'] = exit_code
        report['gradle_help_log_tail'] = log
        if not ok:
            raise RepairRefused('GRADLE_HELP_FAILED')
        if sha(read_wrapper(path)) != sha(after):
            raise RepairRefused('WRAPPER_CHANGED_DURING_VERIFICATION')
        report['status'] = 'VERIFIED_SCOPED_GRADLE_HELP_ONLY'
        report['reason'] = 'SCANNER_PASSED_AND_GRADLE_HELP_SUCCEEDED'
    except Exception as exc:
        report['reason'] = str(exc) if isinstance(exc, RepairRefused) else 'UNEXPECTED_VERIFICATION_ERROR_' + type(exc).__name__
        # Never overwrite somebody else's concurrent change during rollback.
        try:
            if sha(read_wrapper(path)) == sha(after):
                atomic_replace(path, before)
                report['status'] = 'FAILED_AND_WRAPPER_ROLLED_BACK'
            elif sha(read_wrapper(path)) == sha(before):
                report['status'] = 'FAILED_NO_WRAPPER_CHANGE'
            else:
                report['status'] = 'MANUAL_RECOVERY_REQUIRED_WRAPPER_CHANGED'
        except (OSError, RepairRefused):
            report['status'] = 'MANUAL_RECOVERY_REQUIRED_ROLLBACK_ERROR'
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan', help='Read-only scan, diff, and approval token')
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    e = sub.add_parser('execute', help='Apply, verify real Gradle help, rollback on failure')
    e.add_argument('--plan', type=Path, required=True)
    e.add_argument('--approve', required=True)
    e.add_argument('--trust-disposable-project', action='store_true', required=True,
                   help='Acknowledge that executing Gradle runs build logic; use a disposable trusted app')
    e.add_argument('--report', type=Path, required=True)
    r = sub.add_parser('recover', help='Inspect or explicitly restore original wrapper bytes from backup')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--approve', required=True)
    r.add_argument('--restore', action='store_true', help='Explicitly restore original wrapper from valid backup')
    r.add_argument('--trust-disposable-project', action='store_true',
                   help='Required with --restore; recovery does not execute Gradle')
    r.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            result = make_plan(args.project)
            store_json_exclusive(args.output, result)
            print(result['status'], result['reason'], 'plan_id=' + result['plan_id'])
            if result['diff']:
                print(result['diff'])
            return 0 if result['status'] in ('NO_REPAIR_NEEDED', 'READY_FOR_APPROVAL') else 2
        if args.report.exists() or args.report.is_symlink() or args.report.absolute() == args.plan.absolute():
            raise RepairRefused('REPORT_PATH_UNAVAILABLE')
        if args.command == 'recover':
            if args.restore and not args.trust_disposable_project:
                raise RepairRefused('RESTORE_REQUIRES_EXPLICIT_TRUST')
            report = recover(args.plan, args.approve, restore=args.restore)
            store_json_exclusive(args.report, report)
            print(report['status'], report['reason'])
            return 0 if report['status'] in ('ORIGINAL_ALREADY_PRESENT',
                                             'RESTORABLE_WRAPPER_AFTER_IMAGE',
                                             'WRAPPER_RESTORED_FROM_BACKUP') else 2
        report = execute(args.plan, args.approve)
        store_json_exclusive(args.report, report)
        print(report['status'], report['reason'])
        return 0 if report['status'] == 'VERIFIED_SCOPED_GRADLE_HELP_ONLY' else 2
    except (RepairRefused, OSError, ValueError, TypeError) as exc:
        print('REPAIR_INPUT_ERROR:', str(exc), file=sys.stderr)
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
