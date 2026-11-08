"""Read-only composition of existing R02 and Windows R03/R04 evidence.

No new compatibility policy, build execution, automatic remediation or release gate.
The legacy ``rn-readiness`` and ``nativory-windows-doctor`` contracts are unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cli import run as run_r02
from .collector import ProjectInputError
from .report import to_dict as r02_to_dict
from .windows_native_doctor import InputError as DoctorInputError, diagnose as native_diagnose


class InputError(ValueError):
    """Invalid command line or unsupported evidence combination."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def _parser() -> _Parser:
    parser = _Parser(prog="nativory", description="Scoped, read-only Android build evidence (not release certification)")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    scan = commands.add_parser("scan", help="Compose R02 and optional Windows R03/R04 triage")
    scan.add_argument("project", nargs="?", default=".", help="Root of a React Native project")
    scan.add_argument("--build-log", type=Path, help="Failed Windows native build log; required for R03/R04")
    scan.add_argument("--cmake-cache", type=Path, action="append", default=[], help="CMakeCache.txt from the same failed attempt; repeatable")
    scan.add_argument("--ninja-version", type=str, help="Operator-supplied Ninja version, not independently verified")
    scan.add_argument("--ninja-dir", type=str, help="Windows Ninja working directory if absent from log")
    scan.add_argument("--json", dest="json_output", action="store_true", help="Deterministic JSON report")
    return parser


def diagnose(
    project: str | Path,
    *,
    build_log: Path | None = None,
    cmake_caches: list[Path] | None = None,
    ninja_version: str | None = None,
    ninja_dir: str | None = None,
) -> tuple[dict, int]:
    """Create independent scoped reports; never infer overall build health.

    Exit codes: 0 scoped evaluations completed without flagged signals;
    2 definite R02 minimum compatibility violation; 3 review/unknown;
    4 invalid input (handled by ``main``). A 0 is NOT build success.
    """
    caches = list(cmake_caches or [])
    if build_log is None and (caches or ninja_version is not None or ninja_dir is not None):
        raise InputError("--cmake-cache, --ninja-version and --ninja-dir require --build-log")

    r02 = r02_to_dict(run_r02(str(project)))
    r02_status = r02["status"]
    if r02_status not in {"checks_passed", "blocked", "unknown"}:
        raise InputError("Unexpected R02 report status; refusing to summarize")

    if build_log is None:
        windows = {
            "scope": "WINDOWS_NATIVE_LOG_TRIAGE_ONLY",
            "status": "NOT_EVALUATED",
            "reason": "No --build-log provided; R03/R04 were not executed.",
            "findings": [],
        }
        native_statuses = []
    else:
        windows = native_diagnose(
            Path(project), build_log, caches,
            ninja_version=ninja_version, ninja_dir=ninja_dir,
        )
        native_statuses = [finding["status"] for finding in windows["findings"]]
        valid = {"SUSPECTED", "RISK_SIGNAL", "NOT_EVALUATED", "NO_MATCH"}
        if not native_statuses or any(status not in valid for status in native_statuses):
            raise InputError("Unexpected Windows doctor findings; refusing to summarize")

    if r02_status == "blocked":
        verdict, code = "R02_INCOMPATIBLE", 2
    elif r02_status != "checks_passed" or build_log is None or any(
        status != "NO_MATCH" for status in native_statuses
    ):
        verdict, code = "REVIEW_REQUIRED", 3
    else:
        verdict, code = "SCOPED_EVALUATIONS_COMPLETED", 0

    result = {
        "schema_version": "0.1",
        "scope": "NATIVORY_SCOPED_DIAGNOSIS_ONLY",
        "read_only": True,
        "summary": {
            "verdict": verdict,
            "r02_status": r02_status,
            "windows_triage_performed": build_log is not None,
            "windows_rule_statuses": native_statuses,
            "android_build_verified": False,
            "apk_aab_verified": False,
            "runtime_verified": False,
            "release_readiness_verified": False,
        },
        "components": {
            "r02_agp_gradle": r02,
            "windows_native_log_triage": windows,
        },
        "limitations": [
            "R02 assesses an AGP/Gradle minimum only, not effective runtime build configuration.",
            "R03/R04 correlate selected Windows log signatures; SUSPECTED is not root-cause proof.",
            "NO_MATCH means only that the configured signatures were not observed, not build health.",
            "No Gradle/CMake/Ninja/Node execution, APK/AAB inspection or repairs performed.",
            "Neither verdict nor exit code 0 certifies an Android build, runtime or release.",
        ],
    }
    return result, code


def _text_report(report: dict) -> str:
    summary = report["summary"]
    output = [
        "Nativory / Unified Scoped Diagnosis (read-only)",
        f"Verdict: {summary['verdict']}",
        f"R02 AGP/Gradle: {summary['r02_status']}",
    ]
    windows = report["components"]["windows_native_log_triage"]
    if not summary["windows_triage_performed"]:
        output.append("R03/R04 Windows: NOT_EVALUATED (no build log provided)")
    else:
        for item in windows["findings"]:
            output.append(f"{item['rule']}: {item['status']} - {item['summary']}")
    output.append("NOT VERIFIED: Android build, APK/AAB, runtime, release readiness, root-cause certainty.")
    return "\n".join(output)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        report, code = diagnose(
            args.project,
            build_log=args.build_log,
            cmake_caches=args.cmake_cache,
            ninja_version=args.ninja_version,
            ninja_dir=args.ninja_dir,
        )
    except (InputError, ProjectInputError, DoctorInputError, OSError) as exc:
        print(f"INPUT ERROR: {exc}", file=sys.stderr)
        return 4
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) if args.json_output else _text_report(report))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
