"""Smoke-check all three installed CLI entrypoints from an isolated wheel.

Run with: python scripts/wheel_smoke.py
This deliberately avoids the editable install used for the pytest job.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args: object, cwd: Path | None = None, expected: int = 0) -> str:
    command = [str(arg) for arg in args]
    print("$", " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != expected:
        raise RuntimeError(
            f"Expected exit {expected}, got {completed.returncode}: {command!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="nativory-wheel-smoke-") as directory:
        workspace = Path(directory)
        wheels = workspace / "wheels"
        wheels.mkdir()
        venv = workspace / "venv"

        # Building the wheel does not exercise Python imports from the checkout.
        run(sys.executable, "-m", "pip", "wheel", str(repo), "--no-deps", "--wheel-dir", wheels)
        built = list(wheels.glob("rn_readiness_spike-*.whl"))
        if len(built) != 1:
            raise RuntimeError(f"Expected exactly one wheel, got {built!r}")

        run(sys.executable, "-m", "venv", venv)
        scripts = venv / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("rn-readiness.exe" if os.name == "nt" else "rn-readiness")
        unified_cli = scripts / ("nativory.exe" if os.name == "nt" else "nativory")
        native_cli = scripts / (
            "nativory-windows-doctor.exe" if os.name == "nt" else "nativory-windows-doctor"
        )
        run(
            python, "-m", "pip", "install", "--no-index", "--find-links", wheels,
            "rn-readiness-spike", cwd=workspace,
        )
        run(
            python, "-c",
            "from importlib.metadata import version; "
            "from rn_readiness import __version__; "
            "assert version('rn-readiness-spike') == __version__",
            cwd=workspace,
        )
        run(
            python, "-c",
            "from rn_readiness.policy import load_agp_gradle_policy; "
            "assert load_agp_gradle_policy().minimum_by_series['9.2'] == '9.4.1'",
            cwd=workspace,
        )
        # Every declared script must be present in the installed wheel and
        # maintain the documented CLI usage-error exit code.
        for entrypoint in (cli, unified_cli, native_cli):
            if not entrypoint.is_file():
                raise RuntimeError(f"Installed entrypoint missing: {entrypoint.name}")
            run(entrypoint, "--help", cwd=workspace)
            run(entrypoint, "--not-a-valid-option", cwd=workspace, expected=4)

        # Exercise the installed console entrypoint against a minimal actual scan.
        project = workspace / "fixture"
        android = project / "android"
        android.mkdir(parents=True)
        (android / "build.gradle").write_text(
            "plugins { id 'com.android.application' version '9.2.0' apply false }\n",
            encoding="utf-8",
        )
        wrapper = android / "gradle/wrapper/gradle-wrapper.properties"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(
            "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\n",
            encoding="utf-8",
        )
        result = json.loads(run(cli, "scan", project, "--json", cwd=workspace))
        if result.get("status") != "checks_passed":
            raise RuntimeError(f"Installed CLI did not pass fixture scan: {result!r}")

        # The unified CLI without a native log must report NOT_EVALUATED, not
        # a healthy-build verdict. Preserve exact R02 component parity.
        before = {
            str(p.relative_to(project)): p.read_bytes()
            for p in project.rglob("*") if p.is_file()
        }
        unified_without_log = json.loads(run(
            unified_cli, "scan", project, "--json", cwd=workspace, expected=3,
        ))
        if unified_without_log["components"]["r02_agp_gradle"] != result:
            raise RuntimeError("Installed unified CLI changed R02 component results")
        if (
            unified_without_log["summary"]["verdict"] != "REVIEW_REQUIRED"
            or unified_without_log["components"]["windows_native_log_triage"]["status"]
            != "NOT_EVALUATED"
        ):
            raise RuntimeError("Missing build log was incorrectly treated as evaluated")

        # A synthetic Windows Ninja failure exercises the installed doctor
        # without running Gradle, Ninja, CMake or any project executable.
        build_log = workspace / "failed-build.log"
        build_log.write_text(
            "ninja: error: mkdir(" + "x" * 280 + "): No such file or directory\n",
            encoding="utf-8",
        )
        native_args = (
            "--build-log", build_log,
            "--ninja-version", "1.10.2",
            "--ninja-dir", r"C:\nv\android\app\.cxx\Debug\arm64-v8a",
        )
        doctor = json.loads(run(
            native_cli, "--project", project, *native_args,
            "--json", cwd=workspace,
        ))
        statuses = {item["rule"]: item["status"] for item in doctor["findings"]}
        if statuses != {
            "R03_WINDOWS_NDK_PATH": "NOT_EVALUATED",
            "R04_NINJA_LONG_PATH": "SUSPECTED",
        } or doctor["read_only"] is not True:
            raise RuntimeError(f"Installed Windows doctor returned unexpected findings: {statuses!r}")

        unified_with_log = json.loads(run(
            unified_cli, "scan", project, *native_args,
            "--json", cwd=workspace, expected=3,
        ))
        if unified_with_log["components"]["windows_native_log_triage"] != doctor:
            raise RuntimeError("Installed unified CLI changed Windows doctor results")
        if unified_with_log["components"]["r02_agp_gradle"] != result:
            raise RuntimeError("Installed unified CLI changed R02 results with a log")
        summary = unified_with_log["summary"]
        if summary["verdict"] != "REVIEW_REQUIRED" or any(
            summary[flag] is not False for flag in (
                "android_build_verified", "apk_aab_verified",
                "runtime_verified", "release_readiness_verified",
            )
        ):
            raise RuntimeError("Native triage incorrectly certified build/release readiness")

        after = {
            str(p.relative_to(project)): p.read_bytes()
            for p in project.rglob("*") if p.is_file()
        }
        if after != before:
            raise RuntimeError("Installed CLI modified the fixture project")

        print("NATIVORY WHEEL SMOKE PASSED (all three installed CLIs)", flush=True)


if __name__ == "__main__":
    main()
