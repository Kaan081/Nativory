"""Run trace-ndk on frozen corpus checkouts (skip clone)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import os
import tempfile

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
            env={**dict(**__import__("os").environ), "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            record["trace"] = {"error": proc.stderr.strip() or proc.stdout.strip()}
        else:
            record["trace"] = json.loads(proc.stdout)
        record["node_modules_present"] = (scan / "node_modules").is_dir()
        results.append(record)

    RESULTS.write_text(
        json.dumps(
            {
                "corpus_id": spec["corpus_id"],
                "frozen_at": spec["frozen_at"],
                "tool_commit": spec["tool_commit"],
                "checkout_root": str(CHECKOUT_ROOT),
                "results": results,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {RESULTS} ({len(results)} repos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
