"""Unified composition contract: existing R02/doctor are not modified or executed as builds."""
import json

import pytest

from rn_readiness import unified_cli


def _r02(status="checks_passed"):
    return {"schema_version": "0.2", "scope": "R02_AGP_GRADLE_MINIMUM_ONLY",
            "status": status, "findings": [{"rule_id": "R02_AGP_GRADLE_MINIMUM", "status": status}]}


def _windows(left="NO_MATCH", right="NO_MATCH"):
    return {"schema_version": "1", "scope": "WINDOWS_NATIVE_LOG_TRIAGE_ONLY", "read_only": True,
            "findings": [
                {"rule": "R03_WINDOWS_NDK_PATH", "status": left, "summary": "Scoped R03"},
                {"rule": "R04_NINJA_LONG_PATH", "status": right, "summary": "Scoped R04"},
            ]}


@pytest.fixture
def fake_scanners(monkeypatch):
    calls = []

    def r02(path):
        calls.append(("r02", path))
        return "R02_RETURN_VALUE"

    def r02_serialized(value):
        assert value == "R02_RETURN_VALUE"
        return _r02()

    def windows(project, log, caches, ninja_version=None, ninja_dir=None):
        calls.append(("windows", project, log, caches, ninja_version, ninja_dir))
        return _windows()

    monkeypatch.setattr(unified_cli, "run_r02", r02)
    monkeypatch.setattr(unified_cli, "r02_to_dict", r02_serialized)
    monkeypatch.setattr(unified_cli, "native_diagnose", windows)
    return calls


def test_r02_only_is_partial_and_native_not_called(fake_scanners, capsys):
    code = unified_cli.main(["scan", "C:/project", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 3
    assert report["summary"]["verdict"] == "REVIEW_REQUIRED"
    assert report["summary"]["windows_triage_performed"] is False
    assert report["components"]["windows_native_log_triage"]["status"] == "NOT_EVALUATED"
    assert report["summary"]["android_build_verified"] is False
    assert fake_scanners == [("r02", "C:/project")]


def test_scoped_no_match_does_not_claim_build_pass(fake_scanners, capsys):
    code = unified_cli.main(["scan", "C:/project", "--build-log", "failed.log", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["summary"]["verdict"] == "SCOPED_EVALUATIONS_COMPLETED"
    assert all(result["summary"][k] is False for k in (
        "android_build_verified", "apk_aab_verified", "runtime_verified", "release_readiness_verified"
    ))
    assert len(fake_scanners) == 2


@pytest.mark.parametrize("r02_status,expected", [("blocked", 2), ("unknown", 3)])
def test_r02_exit_precedence(fake_scanners, monkeypatch, r02_status, expected):
    monkeypatch.setattr(unified_cli, "r02_to_dict", lambda _: _r02(r02_status))
    report, code = unified_cli.diagnose("C:/project", build_log=unified_cli.Path("log.txt"))
    assert code == expected
    if expected == 2:
        assert report["summary"]["verdict"] == "R02_INCOMPATIBLE"


@pytest.mark.parametrize("state", ["SUSPECTED", "RISK_SIGNAL", "NOT_EVALUATED"])
def test_windows_signals_need_review(fake_scanners, monkeypatch, state):
    monkeypatch.setattr(unified_cli, "native_diagnose", lambda *a, **k: _windows(state))
    report, code = unified_cli.diagnose("C:/project", build_log=unified_cli.Path("log.txt"))
    assert code == 3
    assert report["summary"]["verdict"] == "REVIEW_REQUIRED"


def test_invalid_arg_combo_refuses_without_scanning(fake_scanners, capsys):
    assert unified_cli.main(["scan", "C:/project", "--ninja-version", "1.10.2"]) == 4
    assert "require --build-log" in capsys.readouterr().err
    assert not fake_scanners


def test_unknown_cli_argument_returns_4(fake_scanners, capsys):
    assert unified_cli.main(["scan", "--pretend-repair"]) == 4
    assert "INPUT ERROR" in capsys.readouterr().err
    assert not fake_scanners


def test_unknown_doctor_result_fails_closed(fake_scanners, monkeypatch):
    monkeypatch.setattr(unified_cli, "native_diagnose", lambda *a, **k: _windows("HEALTHY"))
    with pytest.raises(unified_cli.InputError, match="Unexpected Windows"):
        unified_cli.diagnose("C:/project", build_log=unified_cli.Path("log.txt"))


def test_report_stable_and_no_raw_input_echo(fake_scanners, capsys):
    args = ["scan", "C:/Users/Private Person/secret", "--build-log", "private-build.log", "--json"]
    assert unified_cli.main(args) == 0
    first = capsys.readouterr().out
    assert unified_cli.main(args) == 0
    second = capsys.readouterr().out
    assert first == second
    assert "Private Person" not in first
    assert "private-build.log" not in first


def test_text_report_discloses_limits(fake_scanners, capsys):
    assert unified_cli.main(["scan"]) == 3
    out = capsys.readouterr().out
    assert "NOT VERIFIED" in out
    assert "NOT_EVALUATED" in out
