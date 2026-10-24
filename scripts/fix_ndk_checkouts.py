"""Re-clone corpus entries that are missing or on the wrong SHA/remote."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "corpus" / "NDK_CORPUS_FREEZE_v1.json"
CHECKOUT_ROOT = Path(os.environ.get(
    "NDK_CORPUS_ROOT",
    str(Path(tempfile.gettempdir()) / "rn_readiness_ndk_corpus_v1"),
))


def head_sha(dest: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=dest,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def remote_url(dest: Path) -> str | None:
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=dest,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def clone_repo(repo: str, sha: str, dest: Path) -> str | None:
    if dest.exists():
        try:
            shutil.rmtree(dest)
        except OSError:
            pass
    if dest.exists():
        alt = dest.with_name(dest.name + "__retry")
        shutil.rmtree(alt, ignore_errors=True)
        dest = alt
    url = f"https://github.com/{repo}.git"
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "config", "core.longpaths", "true"], cwd=dest, check=False)
    init = subprocess.run(["git", "init"], cwd=dest, capture_output=True, text=True)
    if init.returncode != 0:
        return init.stderr.strip()
    remote = subprocess.run(["git", "remote", "add", "origin", url], cwd=dest, capture_output=True, text=True)
    if remote.returncode != 0:
        return remote.stderr.strip()
    fetch = subprocess.run(
        ["git", "fetch", "--depth", "1", "origin", sha],
        cwd=dest,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        proc = subprocess.run(["git", "clone", url, str(dest)], capture_output=True, text=True)
        if proc.returncode != 0:
            return proc.stderr.strip() or proc.stdout.strip()
    else:
        checkout = subprocess.run(
            ["git", "checkout", "--force", "FETCH_HEAD"],
            cwd=dest,
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            return checkout.stderr.strip()
        if head_sha(dest) != sha:
            return f"head mismatch after shallow fetch: {head_sha(dest)}"
        expected_remote = url.replace(".git", "")
        got = remote_url(dest) or ""
        if expected_remote not in got.replace(".git", ""):
            return f"unexpected remote: {got}"
        return None
    checkout = subprocess.run(
        ["git", "checkout", "--force", sha],
        cwd=dest,
        capture_output=True,
        text=True,
    )
    if checkout.returncode != 0:
        return checkout.stderr.strip()
    if head_sha(dest) != sha:
        return f"head mismatch after checkout: {head_sha(dest)}"
    expected_remote = url.replace(".git", "")
    got = remote_url(dest) or ""
    if expected_remote not in got.replace(".git", ""):
        return f"unexpected remote: {got}"
    return None


def main() -> int:
    spec = json.loads(CORPUS.read_text(encoding="utf-8"))
    for entry in spec["repos"]:
        slug = entry["repo"].replace("/", "__")
        dest = CHECKOUT_ROOT / slug
        ok = (
            (dest / ".git").exists()
            and head_sha(dest) == entry["sha"]
            and (remote_url(dest) or "").endswith(f"{entry['repo']}.git")
        )
        if ok:
            print(f"OK {entry['repo']}")
            continue
        print(f"FIX {entry['repo']} ...")
        err = clone_repo(entry["repo"], entry["sha"], dest)
        if err:
            print(f"  FAIL: {err}")
        else:
            print(f"  done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
