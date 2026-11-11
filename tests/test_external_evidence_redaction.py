"""External AGP catalog provenance must not expose local host paths."""

import json
import os
from pathlib import Path

import pytest

from rn_readiness.cli import run
from rn_readiness.collector import _relative_source
from rn_readiness.models import ResolutionStatus
from rn_readiness.report import to_json, to_text
from rn_readiness.unified_cli import diagnose


def _external_project(tmp_path: Path, layout: str, catalog_value: str) -> tuple[Path, Path]:
    project = tmp_path / "app"
    android = project / "android"
    android.mkdir(parents=True)

    # This dependency deliberately lies outside the scanned project root.
    external = (
        tmp_path / "private-user-home" / "secret-workspace"
        / "node_modules" / "@react-native" / "gradle-plugin"
    )
    catalog = external / "gradle" / "libs.versions.toml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(f'[versions]\nagp = "{catalog_value}"\n', encoding="utf-8")

    if layout == "absolute":
        include_path = external.as_posix()
    elif layout == "relative":
        include_path = Path(os.path.relpath(external, android)).as_posix()
    else:
        raise AssertionError(layout)

    (android / "settings.gradle").write_text(
        f'pluginManagement {{ includeBuild("{include_path}") }}\n', encoding="utf-8"
    )
    (android / "build.gradle").write_text(
        'buildscript { dependencies { classpath("com.android.tools.build:gradle") } }\n',
        encoding="utf-8",
    )
    wrapper = android / "gradle/wrapper/gradle-wrapper.properties"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\n',
        encoding="utf-8",
    )
    return project, external


@pytest.mark.parametrize("layout", ["absolute", "relative"])
@pytest.mark.parametrize("agp,expected_status", [
    ("9.2.1", ResolutionStatus.RESOLVED),
    ("not-a-version", ResolutionStatus.MALFORMED_EVIDENCE),
])
def test_external_catalog_keeps_evidence_but_redacts_host_path(
    tmp_path: Path, layout: str, agp: str, expected_status: ResolutionStatus
) -> None:
    project, external = _external_project(tmp_path, layout, agp)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    result = run(str(project))
    assert result.agp.resolution_status is expected_status
    if expected_status is ResolutionStatus.RESOLVED:
        assert result.agp.value == agp
    else:
        assert result.agp.value is None

    catalog_evidence = [e for e in result.agp.evidence if e.scope.value == "local_dependency"]
    assert len(catalog_evidence) == 1
    assert catalog_evidence[0].source == "external_dependency/libs.versions.toml"
    assert catalog_evidence[0].resolution_path[-1] == "gradle/libs.versions.toml"

    r02_json = to_json(result)
    r02_text = to_text(result)
    combined, _ = diagnose(str(project))
    combined_json = json.dumps(combined, ensure_ascii=False)
    assert combined["components"]["r02_agp_gradle"] == json.loads(r02_json)
    for output in (r02_json, r02_text, combined_json):
        assert "external_dependency/libs.versions.toml" in output
        assert "private-user-home" not in output
        assert "secret-workspace" not in output
        assert external.as_posix() not in output
        assert str(tmp_path) not in output

    assert to_json(run(str(project))) == r02_json
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_in_project_provenance_remains_relative(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    assert _relative_source(repo, repo / "android/settings.gradle") == "android/settings.gradle"
