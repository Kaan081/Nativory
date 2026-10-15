"""Regression tests for representative synthetic Android/React Native layouts."""
from pathlib import Path

import pytest

from rn_readiness.cli import run
from rn_readiness.models import CheckStatus, ResolutionStatus, RuleStatus
from rn_readiness.report import to_dict, to_json


def _wrapper(root: Path, version: str) -> None:
    path = root / "android/gradle/wrapper/gradle-wrapper.properties"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{version}-bin.zip\n",
        encoding="utf-8",
    )


def _dynamic_settings(style: str) -> str:
    if style == "variable":
        return '''pluginManagement {
    def reactNativeGradlePlugin = new File(
        providers.exec {
            workingDir(rootDir)
            commandLine("node", "--print", "require.resolve('@react-native/gradle-plugin/package.json', { paths: [require.resolve('react-native/package.json')] })")
        }.standardOutput.asText.get().trim()
    ).getParentFile().absolutePath
    includeBuild(reactNativeGradlePlugin)
}
plugins { id("com.facebook.react.settings") }
'''
    if style == "inline":
        return '''pluginManagement {
    includeBuild(new File(["node", "--print", "require.resolve('@react-native/gradle-plugin/package.json', { paths: [require.resolve('react-native/package.json')] })"].execute(null, rootDir).text.trim()).getParentFile().toString())
}
plugins { id("com.facebook.react.settings") }
includeBuild(new File(["node", "--print", "require.resolve('@react-native/gradle-plugin/package.json', { paths: [require.resolve('react-native/package.json')] })"].execute(null, rootDir).text.trim()).getParentFile())
'''
    raise ValueError(style)


def make_layout(tmp_path: Path, kind: str) -> Path:
    repo = tmp_path / kind
    android = repo / "android"
    android.mkdir(parents=True)

    if kind == "explicit_plugin":
        (android / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") version "9.2.0" apply false }\n',
            encoding="utf-8",
        )
        _wrapper(repo, "9.4.1")
    elif kind == "legacy_classpath":
        (android / "build.gradle").write_text(
            'buildscript { dependencies { classpath("com.android.tools.build:gradle:7.2.1") } }\n',
            encoding="utf-8",
        )
        _wrapper(repo, "7.5.1")
    elif kind == "literal_rn_missing":
        (android / "settings.gradle").write_text(
            'pluginManagement { includeBuild("../node_modules/@react-native/gradle-plugin") }\n'
            'includeBuild("../node_modules/@react-native/gradle-plugin")\n',
            encoding="utf-8",
        )
        (android / "build.gradle").write_text(
            'buildscript { dependencies { classpath("com.android.tools.build:gradle") } }\n',
            encoding="utf-8",
        )
        _wrapper(repo, "9.4.1")
    elif kind in {"dynamic_variable_missing", "dynamic_inline_missing"}:
        style = "variable" if "variable" in kind else "inline"
        (android / "settings.gradle").write_text(_dynamic_settings(style), encoding="utf-8")
        (android / "build.gradle").write_text(
            'buildscript { dependencies { classpath("com.android.tools.build:gradle") } }\n',
            encoding="utf-8",
        )
        _wrapper(repo, "9.3.1")
    elif kind == "versionless_only":
        (android / "build.gradle").write_text(
            'buildscript { dependencies { classpath("com.android.tools.build:gradle") } }\n',
            encoding="utf-8",
        )
        _wrapper(repo, "9.4.1")
    else:
        raise ValueError(kind)

    return repo


@pytest.mark.parametrize(
    "kind,agp,gradle,resolution,status",
    [
        ("explicit_plugin", "9.2.0", "9.4.1", ResolutionStatus.RESOLVED, CheckStatus.CHECKS_PASSED),
        ("legacy_classpath", "7.2.1", "7.5.1", ResolutionStatus.RESOLVED, CheckStatus.CHECKS_PASSED),
        ("literal_rn_missing", None, "9.4.1", ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED, CheckStatus.UNKNOWN),
        ("dynamic_variable_missing", None, "9.3.1", ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED, CheckStatus.UNKNOWN),
        ("dynamic_inline_missing", None, "9.3.1", ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED, CheckStatus.UNKNOWN),
        ("versionless_only", None, "9.4.1", ResolutionStatus.UNSUPPORTED_LAYOUT, CheckStatus.UNKNOWN),
    ],
)
def test_representative_layout(tmp_path, kind, agp, gradle, resolution, status):
    repo = make_layout(tmp_path, kind)
    analysis = run(str(repo))
    assert analysis.agp.value == agp
    assert analysis.gradle.value == gradle
    assert analysis.agp.resolution_status is resolution
    assert analysis.status is status
    body = to_dict(analysis)
    assert body["facts"]["agp"]["resolution_status"] == resolution.value
    if resolution is not ResolutionStatus.RESOLVED:
        assert analysis.finding.status is RuleStatus.NOT_EVALUATED


@pytest.mark.parametrize(
    "kind",
    ["legacy_classpath", "literal_rn_missing", "dynamic_variable_missing", "dynamic_inline_missing", "versionless_only"],
)
def test_layout_scan_is_read_only_and_deterministic(tmp_path, kind):
    repo = make_layout(tmp_path, kind)
    before = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    first = to_json(run(str(repo)))
    second = to_json(run(str(repo)))
    after = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert first == second
    assert before == after
