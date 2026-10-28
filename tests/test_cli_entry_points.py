"""Console script aliases and unchanged JSON CLI contracts after Nativory rebrand."""
from __future__ import annotations

import json
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from importlib import import_module
from pathlib import Path

from rn_readiness.cli import main, run
from rn_readiness.report import to_json, to_text

ROOT = Path(__file__).resolve().parents[1]


def _console_scripts() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return dict(data["project"]["scripts"])


def test_nativory_and_rn_readiness_entry_points_resolve_to_same_callable():
    scripts = _console_scripts()
    assert scripts["nativory"] == scripts["rn-readiness"] == "rn_readiness.cli:main"
    module_name, attr = scripts["nativory"].split(":")
    target = getattr(import_module(module_name), attr)
    assert target is main


def test_pyproject_keeps_distribution_name_and_package():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "rn-readiness-spike"
    assert data["project"]["version"] == "0.1.3"


def test_text_report_header_unchanged_for_legacy_compatibility(tmp_path):
    from tests.test_vertical_slice import make_repo

    repo = make_repo(tmp_path)
    analysis = run(str(repo))
    doc = json.loads(to_json(analysis))
    assert doc["schema_version"] == "0.2"
    assert doc["scope"] == "R02_AGP_GRADLE_MINIMUM_ONLY"
    text = to_text(analysis)
    assert text.startswith("=== RN Readiness / R02 ===")
    assert "NOT VERIFIED" in text


def test_cli_json_exit_code_unchanged(tmp_path, capsys):
    from tests.test_vertical_slice import make_repo

    repo = make_repo(tmp_path)
    assert main(["scan", str(repo), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc.keys()) >= {
        "schema_version",
        "tool_version",
        "scope",
        "status",
        "facts",
        "findings",
        "limitations",
    }
