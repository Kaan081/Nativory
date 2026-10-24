"""Explicit maintenance: never replace an existing checkout."""
from __future__ import annotations
import json, os, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/corpus/NDK_CORPUS_FREEZE_v1.json"
CHECKOUT_ROOT = Path(os.environ.get(
    "NDK_CORPUS_ROOT",
    str(Path(tempfile.gettempdir()) / "rn_readiness_ndk_corpus_v1")
))

def git_info(dest, *args):
    p = subprocess.run(
        ["git", *args], cwd=dest,
        capture_output=True, text=True
    )
    return p.stdout.strip() if p.returncode == 0 else None

def clone_repo(repo: str, sha: str, dest: Path) -> str | None:
    if dest.exists() or dest.is_symlink():
        return "existing checkout protected; manual review required"

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir()
    except OSError as error:
        return f"mkdir_failed: {error}"

    url = f"https://github.com/{repo}.git"

    steps = (
        ["git", "init"],
        ["git", "remote", "add", "origin", url],
        ["git", "fetch", "--depth", "1", "origin", sha],
        ["git", "checkout", "--detach", "FETCH_HEAD"],
    )

    for command in steps:
        p = subprocess.run(
            command, cwd=dest,
            capture_output=True, text=True
        )
        if p.returncode:
            return (
                f"{command[1]}_failed: "
                f"{p.stderr.strip() or p.stdout.strip()}"
            )

    if git_info(dest, "rev-parse", "HEAD") != sha:
        return "checkout SHA mismatch"

    if git_info(dest, "remote", "get-url", "origin") != url:
        return "checkout remote mismatch"

    return None

def main() -> int:
    spec = json.loads(CORPUS.read_text(encoding="utf-8"))
    failed = 0

    for entry in spec["repos"]:
        dest = (
            CHECKOUT_ROOT /
            entry["repo"].replace("/", "__")
        )
        url = f"https://github.com/{entry['repo']}.git"

        if (
            (dest / ".git").exists()
            and git_info(dest, "rev-parse", "HEAD") == entry["sha"]
            and git_info(dest, "remote", "get-url", "origin") == url
        ):
            print(f"OK {entry['repo']}")
            continue

        if dest.exists() or dest.is_symlink():
            print(
                f"HOLD {entry['repo']}: "
                "invalid existing checkout preserved"
            )
            failed += 1
            continue

        print(f"CLONE {entry['repo']} ...")
        error = clone_repo(
            entry["repo"], entry["sha"], dest
        )

        if error:
            print(f"FAIL {entry['repo']}: {error}")
            failed += 1

    if failed:
        print(f"HOLD: {failed} checkout(s) require review")

    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
