import importlib.util, json, subprocess
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

def load(name):
    spec = importlib.util.spec_from_file_location(
        "test_" + name, SCRIPTS / (name + ".py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def manifest(tmp_path):
    p = tmp_path / "freeze.json"
    p.write_text(json.dumps({
        "corpus_id": "FIXTURE",
        "frozen_at": "2026-10-24",
        "tool_commit": "a" * 40,
        "repos": [{
            "repo": "diagnostic/not-real",
            "sha": "a" * 40,
            "scan_subdir": ""
        }]
    }), encoding="utf-8")
    return p

def test_runner_refuses_missing_checkout_preserves_results(tmp_path):
    m = load("run_ndk_corpus")
    m.CORPUS = manifest(tmp_path)
    m.CHECKOUT_ROOT = tmp_path / "none"
    m.RESULTS = tmp_path / "results.json"
    m.RESULTS.write_bytes(b"protected")
    fake = subprocess.CompletedProcess(
        ["git", "clone"], 1, "", "SIMULATED"
    )
    with patch("subprocess.run", return_value=fake):
        assert m.main() != 0
    assert m.RESULTS.read_bytes() == b"protected"

def test_runner_never_clones_missing_checkout(tmp_path):
    m = load("run_ndk_corpus")
    m.CORPUS = manifest(tmp_path)
    m.CHECKOUT_ROOT = tmp_path / "none"
    m.RESULTS = tmp_path / "results.json"
    m.RESULTS.write_bytes(b"protected")
    with patch(
        "subprocess.run",
        side_effect=AssertionError("Git forbidden")
    ):
        assert m.main() != 0
    assert m.RESULTS.read_bytes() == b"protected"

def test_repair_reports_clone_failure(tmp_path):
    m = load("fix_ndk_checkouts")
    m.CORPUS = manifest(tmp_path)
    m.CHECKOUT_ROOT = tmp_path / "missing"
    with patch.object(
        m, "clone_repo", return_value="SIMULATED"
    ):
        assert m.main() != 0

def test_repair_never_deletes_existing_directory(tmp_path):
    m = load("fix_ndk_checkouts")
    dest = tmp_path / "valuable"
    dest.mkdir()
    (dest / "keep.txt").write_text("keep")
    fake = subprocess.CompletedProcess(
        ["git"], 1, "", "SIMULATED"
    )
    with patch("subprocess.run", return_value=fake):
        assert m.clone_repo(
            "diagnostic/not-real", "a" * 40, dest
        )
    assert (dest / "keep.txt").read_text() == "keep"

def test_repair_main_refuses_existing_invalid_checkout(tmp_path):
    m = load("fix_ndk_checkouts")
    m.CORPUS = manifest(tmp_path)
    m.CHECKOUT_ROOT = tmp_path / "checkouts"
    d = m.CHECKOUT_ROOT / "diagnostic__not-real"
    d.mkdir(parents=True)
    (d / "keep.txt").write_text("keep")
    with patch.object(
        m, "clone_repo",
        side_effect=AssertionError("clone forbidden")
    ):
        assert m.main() != 0
    assert (d / "keep.txt").read_text() == "keep"
