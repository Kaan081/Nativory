"""NDK provenance trace: ownership, resolution kind, and false-positive guards."""
import json
from pathlib import Path

import pytest

from rn_readiness.cli import main
from rn_readiness.ndk_collector import trace_ndk
from rn_readiness.ndk_models import NdkOwnerType, NdkResolutionKind
from rn_readiness.ndk_report import to_json
from rn_readiness.cli import run as scan_run


def _android_repo(tmp_path: Path, name: str = "app") -> Path:
    repo = tmp_path / name
    (repo / "android").mkdir(parents=True)
    return repo


def _write_project_gradle(repo: Path, content: str, *, kotlin: bool = False) -> None:
    filename = "build.gradle.kts" if kotlin else "build.gradle"
    (repo / "android" / filename).write_text(content, encoding="utf-8")


def _write_dependency(
    repo: Path,
    package_name: str,
    gradle_content: str,
    *,
    kotlin: bool = False,
) -> None:
    if package_name.startswith("@"):
        org, pkg = package_name.split("/", 1)
        root = repo / "node_modules" / org / pkg
    else:
        root = repo / "node_modules" / package_name
    root.mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"name": package_name}), encoding="utf-8")
    filename = "build.gradle.kts" if kotlin else "build.gradle"
    (root / "android" / filename).parent.mkdir(parents=True, exist_ok=True)
    (root / "android" / filename).write_text(gradle_content, encoding="utf-8")


def test_project_literal_ndk_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'android { ndkVersion "27.1.12297006" }\n')
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.owner == "project"
    assert item.owner_type is NdkOwnerType.PROJECT
    assert item.value == "27.1.12297006"
    assert item.resolution_kind is NdkResolutionKind.LITERAL
    assert item.source == "android/build.gradle"


def test_kotlin_dsl_literal_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'android { ndkVersion = "26.1.10909125" }\n',
        kotlin=True,
    )
    result = trace_ndk(str(repo))
    assert result.declarations[0].resolution_kind is NdkResolutionKind.LITERAL
    assert result.declarations[0].value == "26.1.10909125"


def test_installed_dependency_literal_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_dependency(repo, "@acme/native-lib", 'android { ndkVersion "25.2.9519653" }\n')
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.owner == "@acme/native-lib"
    assert item.owner_type is NdkOwnerType.INSTALLED_DEPENDENCY
    assert item.value == "25.2.9519653"
    assert item.source == "node_modules/@acme/native-lib/android/build.gradle"


def test_project_and_dependency_different_literal_versions(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    _write_dependency(repo, "react-native-foo", 'ndkVersion "26.1.10909125"\n')
    result = trace_ndk(str(repo))
    literals = {d.value for d in result.declarations if d.resolution_kind is NdkResolutionKind.LITERAL}
    assert literals == {"27.1.12297006", "26.1.10909125"}
    assert result.attention_signals == ("dependency_literal_pin_differs_from_project",)


def test_project_and_dependency_same_literal_version(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    _write_dependency(repo, "react-native-foo", 'ndkVersion "27.1.12297006"\n')
    result = trace_ndk(str(repo))
    assert result.attention_signals == ()


def test_root_project_ext_ndk_version(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, "android { ndkVersion rootProject.ext.ndkVersion }\n")
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.resolution_kind is NdkResolutionKind.ROOT_INHERITED
    assert item.value is None


def test_helper_default_expression(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'android { ndkVersion getExtOrDefault("ndkVersion") }\n')
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.resolution_kind is NdkResolutionKind.UNSUPPORTED_EXPRESSION
    assert item.value is None
    assert "getExtOrDefault" in item.resolution_path[-1]


def test_has_property_ndk_version_is_not_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'if (rootProject.hasProperty("ndkVersion")) { println "skip" }\n'
        'def v = findProperty("ndkVersion")\n',
    )
    result = trace_ndk(str(repo))
    assert result.declarations == ()


def test_comments_and_string_literals_are_not_declarations(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        '// ndkVersion "99.0.0"\n'
        'def msg = "ndkVersion 99.0.0"\n'
        'println(msg)\n',
    )
    result = trace_ndk(str(repo))
    assert result.declarations == ()


def test_no_ndk_evidence(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'plugins { id "com.android.application" }\n')
    result = trace_ndk(str(repo))
    assert result.declarations == ()
    assert result.attention_signals == ()


def test_trace_ndk_json_is_deterministic_without_timestamp_or_machine_path(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    _write_dependency(repo, "dep-a", 'ndkVersion "26.0.0"\n')
    a = to_json(trace_ndk(str(repo)))
    b = to_json(trace_ndk(str(repo)))
    assert a == b
    assert str(tmp_path) not in a
    doc = json.loads(a)
    assert doc["scope"] == "NDK_PROVENANCE_TRACE"
    assert "timestamp" not in doc


def test_trace_ndk_does_not_modify_repository(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    before = [(x.relative_to(repo).as_posix(), x.read_bytes()) for x in sorted(repo.rglob("*")) if x.is_file()]
    trace_ndk(str(repo))
    after = [(x.relative_to(repo).as_posix(), x.read_bytes()) for x in sorted(repo.rglob("*")) if x.is_file()]
    assert before == after


def test_existing_r02_scan_unchanged_after_ndk_work(tmp_path):
    repo = _android_repo(tmp_path)
    wrapper = repo / "android/gradle/wrapper"
    wrapper.mkdir(parents=True)
    (repo / "android/build.gradle").write_text(
        'plugins { id "com.android.application" version "9.2.0" apply false }\n',
        encoding="utf-8",
    )
    (wrapper / "gradle-wrapper.properties").write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\n',
        encoding="utf-8",
    )
    analysis = scan_run(str(repo))
    assert analysis.status.value == "checks_passed"


def test_cli_trace_ndk_json(tmp_path, capsys):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    assert main(["trace-ndk", str(repo), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["declarations"][0]["value"] == "27.1.12297006"
