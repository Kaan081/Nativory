"""Regression: RN-relative Node resolution must not be attributed to a sibling plugin.

No Node/Gradle execution or build is required. These tests assert the conservative
fallback contract when a different package target is plausible.
"""
from pathlib import Path

import pytest

from rn_readiness.cli import run
from rn_readiness.models import ResolutionStatus, RuleStatus
from rn_readiness.report import to_dict
from rn_readiness.unified_cli import diagnose


def _project(tmp_path: Path, style: str, *, top_agp: str = "8.7.2") -> Path:
    root = tmp_path / f"nested-rn-{style}"
    android = root / "android"
    wrapper = android / "gradle/wrapper"
    wrapper.mkdir(parents=True)

    if style == "inline":
        settings = '''pluginManagement {
    includeBuild(new File(["node", "--print", "require.resolve('@react-native/gradle-plugin/package.json', { paths: [require.resolve('react-native/package.json')] })"].execute(null, rootDir).text.trim()).getParentFile())
}
plugins { id("com.facebook.react.settings") }
'''
    elif style == "provider":
        settings = '''pluginManagement {
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
    else:
        raise AssertionError(style)
    (android / "settings.gradle").write_text(settings, encoding="utf-8")
    (android / "build.gradle").write_text(
        'buildscript { dependencies { classpath("com.android.tools.build:gradle") } }\n',
        encoding="utf-8",
    )
    (wrapper / "gradle-wrapper.properties").write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.3.1-bin.zip\n',
        encoding="utf-8",
    )
    react_native = root / "node_modules/react-native/package.json"
    react_native.parent.mkdir(parents=True)
    react_native.write_text('{"name":"react-native","version":"0.87.1"}\n', encoding="utf-8")
    _catalog(root / "node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml", top_agp)
    return root


def _catalog(path: Path, agp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[versions]\nagp = "{agp}"\n', encoding="utf-8")


@pytest.mark.parametrize("style", ["inline", "provider"])
@pytest.mark.parametrize("nested_agp", ["9.2.1", "8.7.2"])
def test_nested_plugin_must_not_be_misattributed_to_top_level(tmp_path, style, nested_agp):
    root = _project(tmp_path, style)
    _catalog(
        root / "node_modules/react-native/node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml",
        nested_agp,
    )

    result = run(str(root))
    assert result.agp.value is None
    assert result.agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT
    assert result.finding.status is RuleStatus.NOT_EVALUATED

    combined, exit_code = diagnose(str(root))
    assert combined["components"]["r02_agp_gradle"] == to_dict(result)
    assert combined["summary"]["r02_status"] == "unknown"
    assert combined["summary"]["android_build_verified"] is False
    assert exit_code == 3


@pytest.mark.parametrize("style", ["inline", "provider"])
def test_flat_plugin_remains_supported(tmp_path, style):
    root = _project(tmp_path, style)
    result = run(str(root))
    assert result.agp.value == "8.7.2"
    assert result.agp.resolution_status is ResolutionStatus.RESOLVED
    assert result.finding.status is RuleStatus.CHECKS_PASSED


@pytest.mark.parametrize("style", ["inline", "provider"])
def test_nested_only_is_unknown_not_a_guess(tmp_path, style):
    root = _project(tmp_path, style)
    top = root / "node_modules/@react-native/gradle-plugin"
    import shutil
    shutil.rmtree(top)
    _catalog(
        root / "node_modules/react-native/node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml",
        "9.2.1",
    )
    result = run(str(root))
    assert result.agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT
    assert result.finding.status is RuleStatus.NOT_EVALUATED


def test_redirected_react_native_directory_is_unsupported(tmp_path):
    root = _project(tmp_path, "inline")
    rn = root / "node_modules/react-native"
    target = root / "rn-target"
    rn.rename(target)
    try:
        rn.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unavailable on this runner")
    result = run(str(root))
    assert result.agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT
    assert result.finding.status is RuleStatus.NOT_EVALUATED


def test_nested_plugin_symlink_is_unsupported_even_if_broken(tmp_path):
    root = _project(tmp_path, "inline")
    nested = root / "node_modules/react-native/node_modules/@react-native/gradle-plugin"
    nested.parent.mkdir(parents=True)
    try:
        nested.symlink_to(root / "non-existent-plugin", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unavailable on this runner")
    result = run(str(root))
    assert result.agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT
    assert result.finding.status is RuleStatus.NOT_EVALUATED
