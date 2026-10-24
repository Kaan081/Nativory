"""Run trace-ndk on frozen corpus checkouts (skip clone)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "corpus" / "NDK_CORPUS_FREEZE_v1.json"
CHECKOUT_ROOT = Path(os.environ.get(
    "NDK_CORPUS_ROOT",
    str(Path(tempfile.gettempdir()) / "rn_readiness_ndk_corpus_v1"),
))
RESULTS = ROOT / "docs" / "corpus" / "NDK_CORPUS_RESULTS_v1.json"


def git_head(repo: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def working_tree_dirty(repo: Path) -> bool:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


def main() -> int:
    spec = json.loads(CORPUS.read_text(encoding="utf-8"))
    results: list[dict] = []
    for entry in spec["repos"]:
        slug = entry["repo"].replace("/", "__")
        dest = CHECKOUT_ROOT / slug
        for candidate in (CHECKOUT_ROOT / slug, CHECKOUT_ROOT / f"{slug}__retry"):
            if (candidate / ".git").exists() and git_head(candidate) == entry["sha"]:
                dest = candidate
                break
        record = {
            "repo": entry["repo"],
            "sha": entry["sha"],
            "scan_subdir": entry["scan_subdir"],
        }
        if not (dest / ".git").exists():
            record["node_modules_present"] = False
            record["trace"] = {"error": "checkout_missing"}
            results.append(record)
            continue
        head = git_head(dest)
        if head != entry["sha"]:
            record["checkout_head"] = head
            record["node_modules_present"] = False
            record["trace"] = {"error": f"checkout_sha_mismatch: expected {entry['sha']}, got {head}"}
            results.append(record)
            continue
        scan = dest / entry["scan_subdir"] if entry["scan_subdir"] else dest
        proc = subprocess.run(
            [sys.executable, "-m", "rn_readiness", "trace-ndk", str(scan), "--json"],
            cwd=ROOT,
            env={**dict(**os.environ), "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            record["trace"] = {"error": proc.stderr.strip() or proc.stdout.strip()}
        else:
            record["trace"] = json.loads(proc.stdout)
        record["node_modules_present"] = (scan / "node_modules").is_dir()
        results.append(record)

    if any(isinstance(item.get("trace"), dict) and "error" in item["trace"] for item in results):
        print(f"Skipped writing {RESULTS}: checkout/trace errors present")
        return 1

    if working_tree_dirty(ROOT):
        print(f"Skipped writing {RESULTS}: repository working tree is dirty")
        return 1

    scanner_head = git_head(ROOT)
    if not scanner_head:
        print(f"Skipped writing {RESULTS}: could not resolve repository HEAD")
        return 1

    payload = {
        "corpus_id": spec["corpus_id"],
        "frozen_at": spec["frozen_at"],
        "corpus_freeze_tool_commit": spec["tool_commit"],
        "tool_commit": scanner_head,
        "results": results,
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if any(marker in encoded for marker in ("C:\\Users", "/Users/", "checkout_root")):
        print(f"Skipped writing {RESULTS}: machine-specific path metadata detected")
        return 1

    RESULTS.write_text(encoded, encoding="utf-8")
    print(f"Wrote {RESULTS} ({len(results)} repos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
