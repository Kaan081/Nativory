"""One-off NDK corpus runner (not part of scanner runtime)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "corpus" / "NDK_CORPUS_FREEZE_v1.json"
CHECKOUT_ROOT = ROOT / ".ndk_corpus_checkouts"
RESULTS = ROOT / "docs" / "corpus" / "NDK_CORPUS_RESULTS_v1.json"


def main() -> int:
    spec = json.loads(CORPUS.read_text(encoding="utf-8"))
    CHECKOUT_ROOT.mkdir(exist_ok=True)
    results: list[dict] = []

    for entry in spec["repos"]:
        slug = entry["repo"].replace("/", "__")
        dest = CHECKOUT_ROOT / slug
        url = f"https://github.com/{entry['repo']}.git"
        if not (dest / ".git").exists():
            last_err = ""
            for attempt, clone_cmd in enumerate((
                ["git", "clone", "--filter=blob:none", url, str(dest)],
                ["git", "clone", url, str(dest)],
            )):
                if dest.exists():
                    import shutil
                    shutil.rmtree(dest, ignore_errors=True)
                proc = subprocess.run(clone_cmd, capture_output=True, text=True)
                if proc.returncode == 0:
                    break
                last_err = proc.stderr.strip() or proc.stdout.strip()
            else:
                results.append({
                    "repo": entry["repo"],
                    "sha": entry["sha"],
                    "scan_subdir": entry["scan_subdir"],
                    "node_modules_present": False,
                    "trace": {"error": f"clone_failed: {last_err}"},
                })
                continue
        fetch = subprocess.run(["git", "fetch", "origin", entry["sha"]], cwd=dest, capture_output=True, text=True)
        if fetch.returncode != 0:
            subprocess.run(["git", "fetch", "--all"], cwd=dest, check=False)
        checkout = subprocess.run(
            ["git", "checkout", "--force", entry["sha"]],
            cwd=dest,
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            results.append({
                "repo": entry["repo"],
                "sha": entry["sha"],
                "scan_subdir": entry["scan_subdir"],
                "node_modules_present": False,
                "trace": {"error": f"checkout_failed: {checkout.stderr.strip()}"},
            })
            continue

        scan = dest / entry["scan_subdir"] if entry["scan_subdir"] else dest
        proc = subprocess.run(
            [sys.executable, "-m", "rn_readiness", "trace-ndk", str(scan), "--json"],
            cwd=ROOT,
            env={**dict(**__import__("os").environ), "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            payload = {"error": proc.stderr.strip() or proc.stdout.strip(), "exit_code": proc.returncode}
        else:
            payload = json.loads(proc.stdout)
        node_modules = (scan / "node_modules").is_dir()
        results.append({
            "repo": entry["repo"],
            "sha": entry["sha"],
            "scan_subdir": entry["scan_subdir"],
            "node_modules_present": node_modules,
            "trace": payload,
        })

    RESULTS.write_text(json.dumps({
        "corpus_id": spec["corpus_id"],
        "frozen_at": spec["frozen_at"],
        "tool_commit": spec["tool_commit"],
        "results": results,
    }, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
