"""Smoke-check the built wheel in an isolated, offline-installed venv.

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
        run(
            python, "-m", "pip", "install", "--no-index", "--find-links", wheels,
            "rn-readiness-spike", cwd=workspace,
        )
        run(
            python, "-c",
            "from rn_readiness.policy import load_agp_gradle_policy; "
            "assert load_agp_gradle_policy().minimum_by_series['9.2'] == '9.4.1'",
            cwd=workspace,
        )
        run(cli, "--help", cwd=workspace)
        run(cli, "--not-a-valid-option", cwd=workspace, expected=4)

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

        print("NATIVORY WHEEL SMOKE PASSED", flush=True)


if __name__ == "__main__":
    main()
