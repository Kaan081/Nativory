"""Measure installed-dependency NDK collection phases (offline, not scanner runtime)."""
from __future__ import annotations

import time
from pathlib import Path

from rn_readiness.collector import _safe_read, project_android_root
from rn_readiness import ndk_collector as nc
from rn_readiness.ndk_models import NdkOwnerType


def profile(repo_path: str) -> None:
    repo = Path(repo_path).resolve()
    project = project_android_root(repo)
    stats = {
        "package_roots": 0,
        "packages_json_read": 0,
        "packages_with_gradle": 0,
        "dirs_traversed": 0,
        "gradle_files_found": 0,
        "gradle_files_read": 0,
    }
    times = {
        "package_list_s": 0.0,
        "package_json_s": 0.0,
        "gradle_walk_s": 0.0,
        "gradle_read_s": 0.0,
        "gradle_parse_s": 0.0,
    }

    t_list = time.perf_counter()
    package_roots: list[Path] = []
    for base in nc._node_modules_bases(repo, project):
        package_roots.extend(nc._iter_installed_packages(base / "node_modules"))
    times["package_list_s"] = time.perf_counter() - t_list
    stats["package_roots"] = len(package_roots)

    original_discover = nc._discover_package_gradle_files

    def timed_discover(package_root: Path) -> list[Path]:
        try:
            root = package_root.resolve(strict=False)
        except OSError:
            return []
        found: list[Path] = []

        def walk(directory: Path, depth: int) -> None:
            if depth > nc.PACKAGE_GRADLE_MAX_DEPTH:
                return
            w0 = time.perf_counter()
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name.lower())
            except OSError:
                times["gradle_walk_s"] += time.perf_counter() - w0
                return
            times["gradle_walk_s"] += time.perf_counter() - w0
            stats["dirs_traversed"] += 1
            for entry in entries:
                if entry.is_symlink():
                    continue
                try:
                    entry.relative_to(root)
                except ValueError:
                    continue
                if entry.is_file():
                    if entry.name in ("build.gradle", "build.gradle.kts"):
                        found.append(entry)
                    continue
                if not entry.is_dir():
                    continue
                if entry.name in nc.PACKAGE_GRADLE_PRUNE_DIRS or entry.name.startswith("."):
                    continue
                walk(entry, depth + 1)

        walk(root, 0)
        out = sorted(found, key=lambda path: path.relative_to(root).as_posix().lower())
        stats["gradle_files_found"] += len(out)
        if out:
            stats["packages_with_gradle"] += 1
        return out

    original_package_name = nc._package_name

    def timed_package_name(package_root: Path) -> str | None:
        p0 = time.perf_counter()
        name = original_package_name(package_root)
        times["package_json_s"] += time.perf_counter() - p0
        stats["packages_json_read"] += 1
        return name

    def timed_scan(repo: Path, gradle_path: Path, *, owner: str, owner_type: NdkOwnerType):
        r0 = time.perf_counter()
        try:
            content = _safe_read(gradle_path)
        except OSError:
            content = None
        times["gradle_read_s"] += time.perf_counter() - r0
        if content is None:
            return []
        stats["gradle_files_read"] += 1
        p0 = time.perf_counter()
        out = nc._parse_ndk_lines(content, owner=owner, owner_type=owner_type, source="x")
        times["gradle_parse_s"] += time.perf_counter() - p0
        return out

    nc._discover_package_gradle_files = timed_discover
    nc._package_name = timed_package_name
    original_scan = nc._scan_gradle_file
    nc._scan_gradle_file = timed_scan

    c0 = time.perf_counter()
    nc._collect_dependency_declarations(repo, project)
    collect_s = time.perf_counter() - c0

    nc._discover_package_gradle_files = original_discover
    nc._package_name = original_package_name
    nc._scan_gradle_file = original_scan

    for key, value in stats.items():
        print(f"{key}={value}")
    for key, value in times.items():
        print(f"{key}={value:.3f}")
    print(f"collect_dependency_s={collect_s:.3f}")


if __name__ == "__main__":
    import sys

    profile(sys.argv[1])
