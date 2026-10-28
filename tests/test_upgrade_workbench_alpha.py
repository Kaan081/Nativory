"""Additive Workbench smoke tests: no Gradle, no network, no downloaded artifacts."""
from pathlib import Path
import json
import subprocess
import sys

WB = Path(__file__).resolve().parents[1] / "tools" / "upgrade_workbench"


def invoke(*args):
    return subprocess.run([sys.executable, "-B", *map(str, args)], capture_output=True, text=True, timeout=30)


def test_workbench_self_test():
    result = invoke(WB / "workbench.py", "self-test")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "WORKBENCH_SELF_TEST: PASS 10/10" in result.stdout


def test_native_property_generator_self_test():
    result = invoke(WB / "prepare_ndk_gstring_case.py", "--self-test")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "NDK_CASE_PREPARATION_SELF_TEST: PASS 7/7" in result.stdout


def test_binary_inspector_self_test():
    result = invoke(WB / "inspect_native_artifact.py", "--self-test")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "NATIVE_ARTIFACT_SELF_TEST: PASS 16/16" in result.stdout


def test_native_provenance_self_test():
    result = invoke(WB / "native_provenance.py", "self-test")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "NATIVE_PROVENANCE_SELF_TEST: PASS 12/12" in result.stdout


def test_missing_artifact_fails_closed(tmp_path):
    result = invoke(WB / "workbench.py", "inspect-native", "--artifact", tmp_path / "not-found.aar", "--json")
    assert result.returncode != 0
    assert "INPUT_OR_EXECUTION_ERROR" in result.stderr


def test_known_expo_preflight_never_certifies_release(tmp_path):
    src = tmp_path / 'node_modules' / 'expo-modules-core' / 'expo-module-gradle-plugin' / 'build.gradle.kts'
    src.parent.mkdir(parents=True)
    src.write_text('implementation("io.github.expo:expo-modules-v2-gradle-plugin:0.1.5")\n', encoding='utf-8')
    result = invoke(WB / "workbench.py", "preflight", "--app", tmp_path, "--target-kgp", "2.3.20", "--json")
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence['finding'] == 'KNOWN_HISTORICAL_RISK_PAIR'
    assert evidence['release_readiness'] == 'NOT_VERIFIED'
    assert evidence['effective_kgp'] == 'NOT_VERIFIED'
