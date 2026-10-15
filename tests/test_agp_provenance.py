"""Production-shaped AGP provenance resolution contract for modern React Native."""
import json
import pytest
from pathlib import Path

from rn_readiness.cli import run
from rn_readiness.models import EvidenceScope, ResolutionStatus, RuleStatus
from rn_readiness.report import to_json


def make_modern_rn(tmp_path: Path, *, plugin=True, catalog='agp = "9.2.1"') -> Path:
    repo = tmp_path / "modern-rn"
    android = repo / "android"
    wrapper = android / "gradle/wrapper"
    wrapper.mkdir(parents=True)
    (android / "settings.gradle").write_text(
        'pluginManagement { includeBuild("../node_modules/@react-native/gradle-plugin") }\n'
        'plugins { id("com.facebook.react.settings") }\n'
        "includeBuild('../node_modules/@react-native/gradle-plugin')\n",
        encoding="utf-8",
    )
    (android / "build.gradle").write_text(
        'buildscript { dependencies { classpath("com.android.tools.build:gradle")\n'
        'classpath("com.facebook.react:react-native-gradle-plugin") } }\n',
        encoding="utf-8",
    )
    (wrapper / "gradle-wrapper.properties").write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\n',
        encoding="utf-8",
    )
    if plugin:
        catalog_file = repo / "node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml"
        catalog_file.parent.mkdir(parents=True)
        catalog_file.write_text(f"[versions]\n{catalog}\n", encoding="utf-8")
    return repo


def test_installed_modern_rn_plugin_resolves_agp_with_provenance(tmp_path):
    repo = make_modern_rn(tmp_path)
    analysis = run(str(repo))
    assert analysis.agp.value == "9.2.1"
    assert analysis.agp.resolution_status is ResolutionStatus.RESOLVED
    local = [e for e in analysis.agp.evidence if e.scope is EvidenceScope.LOCAL_DEPENDENCY]
    assert len(local) == 1
    assert local[0].value == "9.2.1"
    assert local[0].source == "node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml"
    assert local[0].resolution_path == (
        "android/settings.gradle includeBuild",
        "@react-native/gradle-plugin",
        "gradle/libs.versions.toml",
    )
    assert analysis.finding.status is RuleStatus.CHECKS_PASSED


def test_missing_local_plugin_never_guesses(tmp_path):
    repo = make_modern_rn(tmp_path, plugin=False)
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_missing_catalog_is_malformed_evidence(tmp_path):
    repo = make_modern_rn(tmp_path, plugin=False)
    (repo / "node_modules/@react-native/gradle-plugin").mkdir(parents=True)
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.MALFORMED_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_malformed_catalog_never_guesses(tmp_path):
    repo = make_modern_rn(tmp_path, catalog='agp = "not-a-version"')
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.MALFORMED_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_project_and_local_dependency_conflict_is_preserved(tmp_path):
    repo = make_modern_rn(tmp_path)
    with (repo / "android/build.gradle").open("a", encoding="utf-8") as f:
        f.write('\nplugins { id "com.android.application" version "8.7.3" apply false }\n')
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.CONFLICTING_EVIDENCE
    values = sorted(e.value for e in analysis.agp.evidence if e.value is not None)
    assert values == ["8.7.3", "9.2.1"]
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_consistent_project_and_local_evidence_resolves(tmp_path):
    repo = make_modern_rn(tmp_path)
    with (repo / "android/build.gradle").open("a", encoding="utf-8") as f:
        f.write('\nplugins { id "com.android.application" version "9.2.1" apply false }\n')
    analysis = run(str(repo))
    assert analysis.agp.value == "9.2.1"
    assert analysis.agp.resolution_status is ResolutionStatus.RESOLVED
    valued = [e for e in analysis.agp.evidence if e.value == "9.2.1"]
    assert {e.scope for e in valued} == {EvidenceScope.DECLARED, EvidenceScope.LOCAL_DEPENDENCY}


def test_interpolated_include_build_is_unsupported_layout(tmp_path):
    repo = make_modern_rn(tmp_path, plugin=False)
    (repo / "android/settings.gradle").write_text(
        'includeBuild("${rootDir}/../node_modules/@react-native/gradle-plugin")\n',
        encoding="utf-8",
    )
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_no_credible_agp_evidence(tmp_path):
    repo = tmp_path / "empty"
    (repo / "android/gradle/wrapper").mkdir(parents=True)
    (repo / "android/gradle/wrapper/gradle-wrapper.properties").write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\n',
        encoding="utf-8",
    )
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.NO_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_provenance_json_is_deterministic(tmp_path):
    repo = make_modern_rn(tmp_path)
    first = to_json(run(str(repo)))
    second = to_json(run(str(repo)))
    assert first == second
    doc = json.loads(first)
    fact = doc["facts"]["agp"]
    assert fact["component"] == "agp"
    assert fact["value"] == "9.2.1"
    assert fact["resolution_status"] == "resolved"
    assert [e["scope"] for e in fact["evidence"]] == ["declared", "local_dependency"]


def test_scan_does_not_modify_modern_repo(tmp_path):
    repo = make_modern_rn(tmp_path)
    before = {p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    run(str(repo))
    after = {p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert before == after


def make_dynamic_rn(tmp_path: Path, *, style: str, plugin: bool = True, catalog='agp = "9.2.1"') -> Path:
    repo = tmp_path / f"dynamic-rn-{style}"
    android = repo / "android"
    wrapper = android / "gradle/wrapper"
    wrapper.mkdir(parents=True)
    if style == "mattermost":
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
    elif style == "metamask":
        settings = '''pluginManagement {
    includeBuild(new File(["node", "--print", "require.resolve('@react-native/gradle-plugin/package.json', { paths: [require.resolve('react-native/package.json')] })"].execute(null, rootDir).text.trim()).getParentFile().toString())
}
plugins { id("com.facebook.react.settings") }
includeBuild(new File(["node", "--print", "require.resolve('@react-native/gradle-plugin/package.json', { paths: [require.resolve('react-native/package.json')] })"].execute(null, rootDir).text.trim()).getParentFile())
'''
    else:
        raise ValueError(style)
    (android / "settings.gradle").write_text(settings, encoding="utf-8")
    (android / "build.gradle").write_text(
        'buildscript { dependencies { classpath("com.android.tools.build:gradle")\n'
        'classpath("com.facebook.react:react-native-gradle-plugin") } }\n',
        encoding="utf-8",
    )
    (wrapper / "gradle-wrapper.properties").write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\n',
        encoding="utf-8",
    )
    if plugin:
        rn_package = repo / "node_modules/react-native/package.json"
        rn_package.parent.mkdir(parents=True)
        rn_package.write_text('{"name":"react-native","version":"0.87.1"}\n', encoding="utf-8")
        catalog_file = repo / "node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml"
        catalog_file.parent.mkdir(parents=True)
        catalog_file.write_text(f"[versions]\n{catalog}\n", encoding="utf-8")
    return repo


@pytest.mark.parametrize("style", ["mattermost", "metamask"])
def test_dynamic_require_resolve_include_build_resolves_local_plugin(tmp_path, style):
    repo = make_dynamic_rn(tmp_path, style=style)
    analysis = run(str(repo))
    assert analysis.agp.value == "9.2.1"
    assert analysis.agp.resolution_status is ResolutionStatus.RESOLVED
    local = [e for e in analysis.agp.evidence if e.scope is EvidenceScope.LOCAL_DEPENDENCY]
    assert len(local) == 1
    assert local[0].source == "node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml"
    assert local[0].resolution_path == (
        "android/settings.gradle dynamic require.resolve includeBuild",
        "@react-native/gradle-plugin",
        "gradle/libs.versions.toml",
    )
    assert analysis.finding.status is RuleStatus.CHECKS_PASSED


@pytest.mark.parametrize("style", ["mattermost", "metamask"])
def test_dynamic_require_resolve_missing_dependency_never_guesses(tmp_path, style):
    repo = make_dynamic_rn(tmp_path, style=style, plugin=False)
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_require_resolve_text_without_linked_include_build_is_not_dynamic_evidence(tmp_path):
    repo = tmp_path / "not-linked"
    android = repo / "android"
    android.mkdir(parents=True)
    (android / "settings.gradle").write_text(
        'def x = "require.resolve(\'@react-native/gradle-plugin/package.json\', { paths: [require.resolve(\'react-native/package.json\')] })"\n',
        encoding="utf-8",
    )
    analysis = run(str(repo))
    assert analysis.agp.resolution_status is ResolutionStatus.NO_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_dynamic_require_resolve_conflict_never_picks_precedence(tmp_path):
    repo = make_dynamic_rn(tmp_path, style="metamask")
    with (repo / "android/build.gradle").open("a", encoding="utf-8") as file:
        file.write('\nplugins { id "com.android.application" version "8.7.3" apply false }\n')
    analysis = run(str(repo))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.CONFLICTING_EVIDENCE
    assert sorted(e.value for e in analysis.agp.evidence if e.value is not None) == ["8.7.3", "9.2.1"]
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_dynamic_require_resolve_is_read_only_and_deterministic(tmp_path):
    repo = make_dynamic_rn(tmp_path, style="mattermost")
    before = {p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    first = to_json(run(str(repo)))
    second = to_json(run(str(repo)))
    after = {p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert first == second
    assert before == after
