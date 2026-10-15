"""R02 acceptance tests; no real Gradle command is run."""
import json
from pathlib import Path

import pytest

from rn_readiness.cli import main, run
from rn_readiness.collector import _strip_comments
from rn_readiness.models import (
    CheckStatus,
    ResolvedFact,
    ResolutionStatus,
    RuleStatus,
)
from rn_readiness.policy import load_agp_gradle_policy
from rn_readiness.report import to_json, to_text
from rn_readiness.rules import compare_versions, evaluate_agp_gradle


def make_repo(tmp_path, agp="9.2.0", gradle="9.4.1", *, kotlin=False):
    repo = tmp_path / "rn-app"
    android = repo / "android"
    wrapper = android / "gradle" / "wrapper"
    wrapper.mkdir(parents=True)
    if agp is not None:
        if kotlin:
            (android / "build.gradle.kts").write_text(
                f'plugins {{ id("com.android.application") version "{agp}" apply false }}\n', encoding="utf-8"
            )
        else:
            (android / "build.gradle").write_text(
                f"plugins {{ id 'com.android.application' version '{agp}' apply false }}\n", encoding="utf-8"
            )
    if gradle is not None:
        (wrapper / "gradle-wrapper.properties").write_text(
            f'distributionUrl=https\\://services.gradle.org/distributions/gradle-{gradle}-bin.zip\n',
            encoding="utf-8",
        )
    return repo


@pytest.mark.parametrize(("agp", "gradle"), [
    ("9.2.0", "9.4.1"), ("9.2.0", "9.5"), ("9.4.0", "9.6.0"),
    ("9.3.2", "9.5"), ("9.1.0", "9.3.1"), ("8.9.2", "8.11.1"),
    ("8.13.0", "8.13"), ("8.0.0", "8.0.0"),
])
def test_compatible_versions(tmp_path, agp, gradle):
    assert run(str(make_repo(tmp_path, agp, gradle))).status is CheckStatus.CHECKS_PASSED


@pytest.mark.parametrize(("agp", "gradle"), [
    ("9.2.0", "9.3.1"), ("9.4.0", "9.4.1"),
    ("8.9.0", "8.11.0"), ("9.1.0", "9.3.0"),
])
def test_blocked_versions(tmp_path, agp, gradle):
    report = run(str(make_repo(tmp_path, agp, gradle)))
    assert report.status is CheckStatus.BLOCKED
    assert report.finding.status is RuleStatus.BLOCKED
    assert "requires Gradle" in report.finding.message


@pytest.mark.parametrize(("agp", "gradle", "reason"), [
    ("9.5.0", "9.7.0", None),
    ("9.2.0-rc01", "9.4.1", ResolutionStatus.MALFORMED_EVIDENCE),
    ("9.2.0", "9.4.1-rc-1", ResolutionStatus.MALFORMED_EVIDENCE),
    (None, "9.4.1", ResolutionStatus.NO_EVIDENCE),
    ("9.2.0", None, ResolutionStatus.NO_EVIDENCE),
])
def test_unresolved_never_passes(tmp_path, agp, gradle, reason):
    analysis = run(str(make_repo(tmp_path, agp, gradle)))
    assert analysis.status is CheckStatus.UNKNOWN
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED
    if reason is not None:
        assert reason in (analysis.agp.resolution_status, analysis.gradle.resolution_status)


def test_alias_is_explicit_unsupported_layout(tmp_path):
    repo = make_repo(tmp_path, agp=None)
    (repo / "android" / "build.gradle.kts").write_text(
        "plugins { alias(libs.plugins.android.application) }\n", encoding="utf-8"
    )
    analysis = run(str(repo))
    assert analysis.agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_alias_does_not_resolve_against_unrelated_classpath(tmp_path):
    repo = make_repo(tmp_path, agp=None)
    (repo / "android" / "build.gradle.kts").write_text(
        "plugins { alias(libs.plugins.android.application) }\n", encoding="utf-8"
    )
    (repo / "android" / "settings.gradle.kts").write_text(
        'dependencies { classpath("com.android.tools.build:gradle:9.2.0") }\n', encoding="utf-8"
    )
    assert run(str(repo)).status is CheckStatus.UNKNOWN


def test_groovy_buildscript_classpath(tmp_path):
    repo = make_repo(tmp_path, agp=None)
    (repo / "android" / "build.gradle").write_text(
        "buildscript { dependencies { classpath 'com.android.tools.build:gradle:9.2.0' } }\n",
        encoding="utf-8",
    )
    analysis = run(str(repo))
    assert analysis.agp.value == "9.2.0"
    assert analysis.agp.resolution_status is ResolutionStatus.RESOLVED
    assert analysis.status is CheckStatus.CHECKS_PASSED


def test_kotlin_plugin(tmp_path):
    assert run(str(make_repo(tmp_path, kotlin=True))).status is CheckStatus.CHECKS_PASSED


def test_conflicting_plugin_versions_never_pass(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "android" / "settings.gradle").write_text(
        "plugins { id 'com.android.library' version '9.1.0' }", encoding="utf-8"
    )
    analysis = run(str(repo))
    assert analysis.agp.resolution_status is ResolutionStatus.CONFLICTING_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_unversioned_plugin_is_unsupported_without_resolution_mechanism(tmp_path):
    repo = make_repo(tmp_path, agp=None)
    (repo / "android" / "build.gradle").write_text(
        "plugins { id 'com.android.application' }", encoding="utf-8"
    )
    assert run(str(repo)).agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT


def test_comments_are_not_evidence(tmp_path):
    repo = make_repo(tmp_path, agp=None)
    (repo / "android" / "build.gradle").write_text(
        "// id 'com.android.application' version '9.2.0'\n"
        "/* classpath 'com.android.tools.build:gradle:9.2.0' */\n",
        encoding="utf-8",
    )
    assert run(str(repo)).agp.resolution_status is ResolutionStatus.NO_EVIDENCE


def test_strip_comments_preserves_non_comment_text():
    assert "plugins" in _strip_comments("plugins {} // note")


def test_non_android_plugin_does_not_match(tmp_path):
    repo = make_repo(tmp_path, agp=None)
    (repo / "android" / "build.gradle").write_text(
        'plugins { id("org.jetbrains.kotlin.android") version "2.2.0" }\n', encoding="utf-8"
    )
    assert run(str(repo)).agp.resolution_status is ResolutionStatus.NO_EVIDENCE


def test_wrapper_missing_distribution_url(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "android" / "gradle/wrapper/gradle-wrapper.properties").write_text(
        "distributionSha256Sum=x\n", encoding="utf-8"
    )
    assert run(str(repo)).gradle.resolution_status is ResolutionStatus.NO_EVIDENCE


def test_wrapper_unsupported_distribution_url(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "android" / "gradle/wrapper/gradle-wrapper.properties").write_text(
        "distributionUrl=../custom-archive.zip\n", encoding="utf-8"
    )
    assert run(str(repo)).gradle.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT


def test_duplicate_wrapper_definitions_are_not_silently_selected(tmp_path):
    repo = make_repo(tmp_path)
    with (repo / "android" / "gradle/wrapper/gradle-wrapper.properties").open("a", encoding="utf-8") as f:
        f.write('distributionUrl=https\\://services.gradle.org/distributions/gradle-9.3.1-bin.zip\n')
    assert run(str(repo)).gradle.resolution_status is ResolutionStatus.CONFLICTING_EVIDENCE


def test_bad_or_unreadable_config_returns_unknown(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "android" / "build.gradle").write_text("X" * 1_000_001, encoding="utf-8")
    analysis = run(str(repo))
    assert analysis.agp.resolution_status is ResolutionStatus.MALFORMED_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_symlink_config_does_not_escape_repository(tmp_path):
    repo = make_repo(tmp_path)
    config = repo / "android" / "build.gradle"
    external = tmp_path / "outside.gradle"
    external.write_text('plugins { id "com.android.application" version "9.2.0" }', encoding="utf-8")
    config.unlink()
    try:
        config.symlink_to(external)
    except OSError:
        pytest.skip("Symlinks unavailable on this platform")
    analysis = run(str(repo))
    assert analysis.agp.resolution_status is ResolutionStatus.MALFORMED_EVIDENCE
    assert analysis.status is CheckStatus.UNKNOWN


def test_direct_android_directory_is_supported(tmp_path):
    repo = make_repo(tmp_path)
    assert run(str(repo / "android")).status is CheckStatus.CHECKS_PASSED


def test_no_modification_of_inspected_repository(tmp_path):
    repo = make_repo(tmp_path)
    before = [(x.relative_to(repo).as_posix(), x.read_bytes()) for x in sorted(repo.rglob("*")) if x.is_file()]
    analysis = run(str(repo))
    after = [(x.relative_to(repo).as_posix(), x.read_bytes()) for x in sorted(repo.rglob("*")) if x.is_file()]
    assert before == after
    assert analysis.status is CheckStatus.CHECKS_PASSED


def test_json_is_deterministic_without_timestamp_or_machine_path(tmp_path):
    repo = make_repo(tmp_path)
    a = to_json(run(str(repo)))
    b = to_json(run(str(repo)))
    assert a == b
    assert str(tmp_path) not in a
    doc = json.loads(a)
    assert doc["schema_version"] == "0.2"
    assert doc["status"] == "checks_passed"
    assert doc["scope"] == "R02_AGP_GRADLE_MINIMUM_ONLY"
    assert doc["facts"]["agp"]["component"] == "agp"
    assert doc["facts"]["agp"]["resolution_status"] == "resolved"
    assert doc["facts"]["agp"]["evidence"][0]["source"] == "android/build.gradle"
    assert "timestamp" not in doc


def test_terminal_does_not_claim_full_release_readiness(tmp_path):
    text = to_text(run(str(make_repo(tmp_path))))
    assert "NOT VERIFIED" in text
    assert "not release readiness" in text


def test_cli_json_and_exit_codes(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert main(["scan", str(repo), "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "checks_passed"
    assert not captured.err

    (repo / "android" / "gradle/wrapper/gradle-wrapper.properties").write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.3.1-bin.zip\n',
        encoding="utf-8",
    )
    assert main([str(repo), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_cli_unknown_exit_three(tmp_path, capsys):
    repo = make_repo(tmp_path, agp=None)
    assert main([str(repo), "--json"]) == 3
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "unknown"
    assert doc["findings"][0]["status"] == "not_evaluated"


def test_missing_directory_exit_four(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "missing")]) == 4
    captured = capsys.readouterr()
    assert "INPUT ERROR" in captured.err
    assert not captured.out


def test_policy_snapshot_matches_authoritative_examples():
    p = load_agp_gradle_policy()
    assert p.minimum_by_series["9.2"] == "9.4.1"
    assert p.minimum_by_series["9.4"] == "9.6.0"
    assert p.minimum_by_series["8.9"] == "8.11.1"
    assert p.source_url.startswith("https://developer.android.com/")


@pytest.mark.parametrize(("a", "b", "expected"), [
    ("9.4.1", "9.4.1", 0), ("9.4.2", "9.4.1", 1), ("9.3.1", "9.4.1", -1),
    ("8.13", "8.9", 1), ("9.4", "9.4.0", 0), ("9.10", "9.9", 1),
])
def test_numeric_version_comparison(a, b, expected):
    assert compare_versions(a, b) == expected


def test_unrecognized_catalog_alias_prevents_false_pass(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "android" / "app").mkdir()
    (repo / "android" / "app" / "build.gradle.kts").write_text(
        "plugins { alias(libs.plugins.agp) }", encoding="utf-8"
    )
    analysis = run(str(repo))
    assert analysis.agp.resolution_status is ResolutionStatus.UNSUPPORTED_LAYOUT
    assert analysis.status is CheckStatus.UNKNOWN


def test_resolved_fact_without_value_does_not_crash():
    missing_value = ResolvedFact("agp", None, ResolutionStatus.RESOLVED)
    gradle = ResolvedFact("gradle", "9.4.1", ResolutionStatus.RESOLVED)
    finding = evaluate_agp_gradle(missing_value, gradle)
    assert finding.status is RuleStatus.NOT_EVALUATED
