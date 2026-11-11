"""Regression: R04 examines every bounded-log mkdir failure and Windows UTF-16 lengths."""
import json
from pathlib import Path, PureWindowsPath

import pytest

from rn_readiness.windows_native_doctor import _r04, diagnose


DIRECTORY = r"C:\nv\android\app\.cxx\Debug\arm64-v8a"


def _failure(relative: str) -> str:
    return f"ninja: error: mkdir({relative}): No such file or directory\n"


def _units(path: str) -> int:
    return len(path.encode("utf-16-le", errors="surrogatepass")) // 2


def test_33rd_failure_can_be_the_longest_path():
    # Old implementation ignored every mkdir error after the first 32.
    long_relative = "objects/" + "x" * 280
    log = _failure("a/b") * 32 + _failure(long_relative)
    finding = _r04(log, "1.10.2", DIRECTORY)
    expected = _units(str(PureWindowsPath(DIRECTORY) / long_relative))
    assert expected > 260
    assert finding["status"] == "SUSPECTED"
    assert finding["evidence"]["longest_mkdir_path_length"] == expected
    assert finding["evidence"]["longest_mkdir_path_length_unit"] == "utf16_code_units"


def test_supplementary_unicode_counts_as_two_windows_utf16_units():
    # 130 supplementary Unicode characters are 260 Windows UTF-16 units.
    relative = "😀" * 130
    path = str(PureWindowsPath(DIRECTORY) / relative)
    assert len(path) < 260
    assert _units(path) >= 260
    finding = _r04(_failure(relative), "1.10.2", DIRECTORY)
    assert finding["status"] == "SUSPECTED"
    assert finding["evidence"]["longest_mkdir_path_length"] == _units(path)


@pytest.mark.parametrize("offset,expected_status", [(-1, "NOT_EVALUATED"), (0, "SUSPECTED")])
def test_ascii_path_boundary_at_260_utf16_units(offset, expected_status):
    prefix = str(PureWindowsPath(DIRECTORY)) + "\\"
    relative = "x" * (260 + offset - _units(prefix))
    assert _units(str(PureWindowsPath(DIRECTORY) / relative)) == 260 + offset
    finding = _r04(_failure(relative), "1.10.2", DIRECTORY)
    assert finding["status"] == expected_status
    assert finding["evidence"]["longest_mkdir_path_length"] == 260 + offset


def test_late_long_match_with_newer_ninja_is_risk_not_old_ninja():
    log = _failure("tiny") * 35 + _failure("x" * 300)
    finding = _r04(log, "1.12.1", DIRECTORY)
    assert finding["status"] == "RISK_SIGNAL"
    assert finding["evidence"]["ninja_version_below_1_12"] is False


def test_full_report_keeps_paths_private_and_read_only(tmp_path: Path):
    project = tmp_path / "project"
    (project / "android").mkdir(parents=True)
    log = tmp_path / "failure.log"
    log.write_text(_failure("😀" * 130), encoding="utf-8")
    report = diagnose(project, log, [], ninja_version="1.10.2", ninja_dir=DIRECTORY)
    ninja = report["findings"][1]
    assert ninja["status"] == "SUSPECTED"
    assert ninja["evidence"]["longest_mkdir_path_length_unit"] == "utf16_code_units"
    assert report["read_only"] is True
    serialized = json.dumps(report, ensure_ascii=False)
    assert DIRECTORY not in serialized
    assert "😀" not in serialized
    assert str(tmp_path) not in serialized


def test_mkdir_signature_without_working_directory_remains_unknown():
    finding = _r04(_failure("x" * 300), "1.10.2", None)
    assert finding["status"] == "NOT_EVALUATED"
    assert finding["evidence"]["longest_mkdir_path_length"] is None
