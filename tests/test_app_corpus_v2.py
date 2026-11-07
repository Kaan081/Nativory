"""Contract tests for offline, reproducible R02 corpus measurement tooling."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "app_corpus_v2.py"
spec = importlib.util.spec_from_file_location("app_corpus_v2", SCRIPT)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
SHA = "a" * 40


def sample_case(**kwargs):
    return {"id": "my-app", "kind": "application", "repository": "team/my-app",
            "commit": SHA, "scan_root": ".", **kwargs}


def fake_report(value="9.2.1"):
    return {"status": "checks_passed", "facts": {
        "agp": {"value": value, "resolution_status": "resolved"},
        "gradle": {"value": "9.4.1", "resolution_status": "resolved"},
    }}


def test_manifest_rejects_unpinned_and_escape_roots(tmp_path):
    manifest = tmp_path / "manifest.json"
    for override in ({"commit": "main"}, {"scan_root": "../outside"},
                     {"scan_root": "/outside"}, {"scan_root": r"C:\outside"},
                     {"scan_root": r"C:relative"}, {"scan_root": r"\outside"},
                     {"scan_root": r"sub\..\escape"}):
        case = sample_case()
        case.update(override)
        manifest.write_text(json.dumps({"schema_version": 1, "cases": [case]}), encoding="utf-8")
        with pytest.raises(ValueError):
            app.load_manifest(manifest)


def test_missing_checkout_is_not_counted_as_scanned(tmp_path):
    result = app.inspect_case(sample_case(), tmp_path)
    assert result["state"] == "missing_checkout"
    assert app.summary([result])["scanned"] == 0


def test_revision_mismatch_prevents_scanning(tmp_path):
    (tmp_path / "my-app").mkdir()
    def forbidden(_root):
        raise AssertionError("Scanner must not execute")
    result = app.inspect_case(sample_case(), tmp_path, scan=forbidden,
                              get_head=lambda _: "b" * 40)
    assert result["state"] == "revision_mismatch"


def test_stable_scans_and_truth_types_are_separate(tmp_path):
    (tmp_path / "my-app").mkdir()
    truth = {"agp": "9.2.1", "method": "manual_declaration", "evidence_ref": "local note"}
    result = app.inspect_case(sample_case(), tmp_path, truth,
                              scan=lambda _: fake_report(), get_head=lambda _: SHA)
    assert result["state"] == "scanned"
    assert result["agreement"] == "match"
    s = app.summary([result])
    assert s["manual_declaration_matches"] == 1
    assert s["gradle_runtime_matches"] == 0
    assert s["build_successes"] == "NOT_MEASURED"


def test_runtime_mismatch_is_not_masked_by_successful_scanner(tmp_path):
    (tmp_path / "my-app").mkdir()
    truth = {"agp": "8.8.0", "method": "gradle_runtime", "evidence_ref": "runtime log"}
    result = app.inspect_case(sample_case(), tmp_path, truth,
                              scan=lambda _: fake_report(), get_head=lambda _: SHA)
    assert result["agreement"] == "mismatch"
    assert app.summary([result])["gradle_runtime_mismatches"] == 1


def test_nondeterministic_scan_fails_closed(tmp_path):
    (tmp_path / "my-app").mkdir()
    values = iter([fake_report(), fake_report("8.7.3")])
    result = app.inspect_case(sample_case(), tmp_path, scan=lambda _: next(values),
                              get_head=lambda _: SHA)
    assert result["state"] == "nondeterministic"
    assert app.summary([result])["scanned"] == 0


def test_truth_fails_on_stale_sha(tmp_path):
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"schema_version": 1, "facts": [{
        "id": "my-app", "commit": "b" * 40,
        "method": "gradle_runtime", "agp": "9.2.1", "evidence_ref": "run.log",
    }]}), encoding="utf-8")
    with pytest.raises(ValueError):
        app.load_truth(truth, [sample_case()])
