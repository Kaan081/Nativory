"""P1 regression: documentation strings must never become R02 declarations."""
from pathlib import Path

import pytest

from rn_readiness.cli import run
from rn_readiness.collector import _gradle_code_without_strings
from rn_readiness.models import ResolutionStatus, RuleStatus
from rn_readiness.report import to_dict
from rn_readiness.unified_cli import diagnose


def _project(tmp_path: Path, contents: str, *, filename: str = "build.gradle", wrapper: str = "9.3.1") -> Path:
    root = tmp_path / "quoted-gradle"
    android = root / "android"
    android.mkdir(parents=True)
    (android / filename).write_text(contents, encoding="utf-8")
    properties = android / "gradle/wrapper/gradle-wrapper.properties"
    properties.parent.mkdir(parents=True)
    properties.write_text(
        f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{wrapper}-bin.zip\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("quote", ['"""', "'''"])
@pytest.mark.parametrize("filename", ["build.gradle", "settings.gradle"])
def test_triple_quoted_plugin_example_is_not_a_declaration(tmp_path, quote, filename):
    root = _project(
        tmp_path,
        f"def example = {quote}plugins {{\n    id 'com.android.application' version '9.2.1'\n}}{quote}\n",
        filename=filename,
    )
    analysis = run(str(root))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.NO_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED

    report, code = diagnose(str(root))
    assert report["components"]["r02_agp_gradle"] == to_dict(analysis)
    assert report["summary"]["r02_status"] == "unknown"
    assert code == 3


@pytest.mark.parametrize("kind", ["classpath", "alias", "includeBuild"])
def test_quoted_expressions_are_not_executable_evidence(tmp_path, kind):
    if kind == "classpath":
        example = "buildscript { dependencies { classpath('com.android.tools.build:gradle:9.2.1') } }"
    elif kind == "alias":
        example = "plugins { alias(libs.plugins.android.application) }"
    else:
        example = 'pluginManagement { includeBuild("../node_modules/@react-native/gradle-plugin") }'
    root = _project(tmp_path, f'def example = """{example}"""\n')
    analysis = run(str(root))
    assert analysis.agp.value is None
    assert analysis.agp.resolution_status is ResolutionStatus.NO_EVIDENCE
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_real_plugin_survives_conflicting_triple_quoted_example(tmp_path):
    root = _project(
        tmp_path,
        'def example = """plugins {\n id "com.android.application" version "8.7.2"\n}"""\n'
        'plugins { id "com.android.application" version "9.2.1" apply false }\n',
        wrapper="9.4.1",
    )
    analysis = run(str(root))
    assert analysis.agp.value == "9.2.1"
    assert analysis.agp.resolution_status is ResolutionStatus.RESOLVED
    assert analysis.finding.status is RuleStatus.CHECKS_PASSED


def test_actual_classpath_keeps_quoted_literal_value(tmp_path):
    root = _project(
        tmp_path,
        '''buildscript { dependencies { classpath("com.android.tools.build:gradle:8.7.2") } }\n''',
        wrapper="9.3.1",
    )
    analysis = run(str(root))
    assert analysis.agp.value == "8.7.2"
    assert analysis.agp.resolution_status is ResolutionStatus.RESOLVED
    assert analysis.finding.status is RuleStatus.CHECKS_PASSED


def test_inline_single_quoted_example_does_not_become_plugin(tmp_path):
    root = _project(
        tmp_path,
        'def sample = "plugins { id \'com.android.application\' version \'9.2.1\' }"\n',
    )
    analysis = run(str(root))
    assert analysis.agp.value is None
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_unterminated_triple_quote_fails_closed(tmp_path):
    root = _project(
        tmp_path,
        'def example = """plugins {\n id "com.android.application" version "9.2.1"\n',
    )
    analysis = run(str(root))
    assert analysis.agp.value is None
    assert analysis.finding.status is RuleStatus.NOT_EVALUATED


def test_string_mask_preserves_offsets_and_executable_keywords():
    code = 'plugins { id "com.android.application" version "9.2.1" }\n' \
           'def example = """plugins {\n id "com.android.application" version "9.9.9"\n}"""\n'
    masked = _gradle_code_without_strings(code)
    assert len(masked) == len(code)
    assert masked.count("id") == 1
    assert "9.9.9" not in masked
