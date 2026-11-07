"""R03/R04 diagnostic pilot: bounded, offline, read-only Windows native build evidence.

This module never executes Gradle, CMake, Ninja, or any other project executable.
A matched signature is a triage clue, not proof of causation or build health.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PureWindowsPath

MAX_LOG_BYTES = 8_000_000
MAX_CACHE_BYTES = 1_000_000
MAX_CACHES = 16

_CPP_UNDEFINED = re.compile(
    r"ld\.lld:\s*error:\s*undefined symbol:\s*"
    r"(?:std::__ndk1\b|__cxa_throw\b|__gxx_personality_v0\b)",
    re.IGNORECASE,
)
_NINJA_MKDIR = re.compile(
    r"ninja:\s*error:\s*mkdir\((.{1,4096}?)\):\s*No such file or directory",
    re.IGNORECASE | re.DOTALL,
)
_NINJA_C = re.compile(
    r'^\s*-C\s*\^?\s*(?:\r?\n\s*)?"(?P<directory>[A-Za-z]:[^"\r\n]+)"',
    re.MULTILINE | re.IGNORECASE,
)
_NDK_CACHE = re.compile(r"^CMAKE_ANDROID_NDK(?::[^=]+)?=(.+)$", re.MULTILINE)
_NDK_DECLARED = re.compile(r"^\s*ndk\.dir\s*=\s*(.+?)\s*$", re.MULTILINE)


class InputError(ValueError):
    """Untrusted or unsupported input; never silently convert it to a finding."""


def _read_bounded(path: Path, limit: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise InputError(f"Missing, nonregular, or symlinked input file: {path.name}")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise InputError(f"Input exceeds {limit} byte limit: {path.name}")
    # Windows PowerShell 5.1 `*> file.log` writes UTF-16 LE with a BOM.
    # Decoding that as UTF-8 silently inserts NULs between ASCII characters,
    # hiding real Ninja/ld.lld failures behind a misleading NO_MATCH.
    if content.startswith(b"\xff\xfe"):
        encoding, payload = "utf-16-le", content[2:]
    elif content.startswith(b"\xfe\xff"):
        encoding, payload = "utf-16-be", content[2:]
    elif content.startswith(b"\xef\xbb\xbf"):
        encoding, payload = "utf-8", content[3:]
    else:
        encoding, payload = "utf-8", content
        if b"\x00" in payload:
            raise InputError(f"Unsupported BOM-less UTF-16 or binary input: {path.name}")
    try:
        return payload.decode(encoding)
    except UnicodeDecodeError as exc:
        raise InputError(f"Invalid {encoding} input: {path.name}") from exc


def _winpath(path: str) -> str:
    # Windows/Gradle logs may render backslashes doubled; do not interpret escape sequences.
    return path.replace("\\\\", "\\")


def _ndk_evidence(project: Path, cache_paths: list[Path]) -> dict:
    paths: list[str] = []
    for cache in cache_paths:
        resolved = cache.resolve(strict=False)
        if not resolved.is_relative_to(project) or cache.is_symlink():
            raise InputError("CMake cache must be a regular file within the project")
        text = _read_bounded(cache, MAX_CACHE_BYTES)
        matches = [value.strip() for value in _NDK_CACHE.findall(text) if value.strip()]
        if len(matches) != 1:
            raise InputError("Each supplied CMake cache must declare exactly one CMAKE_ANDROID_NDK")
        paths.extend(matches)

    normalized = {str(PureWindowsPath(_winpath(value))).casefold() for value in paths}
    declared_path = project / "android" / "local.properties"
    declared_space: bool | None = None
    if declared_path.exists() or declared_path.is_symlink():
        declared = _NDK_DECLARED.findall(_read_bounded(declared_path, MAX_CACHE_BYTES))
        if len(declared) == 1:
            declared_space = bool(re.search(r"\s", declared[0].strip()))

    return {
        "effective_cache_count": len(paths),
        "conflicting_effective_ndk_paths": len(normalized) > 1,
        "effective_ndk_path_contains_whitespace": (
            bool(re.search(r"\s", paths[0])) if paths and len(normalized) == 1 else None
        ),
        "declared_ndk_path_contains_whitespace": declared_space,
    }


def _r03(log: str, ndk: dict) -> dict:
    evidence = {**ndk, "cpp_runtime_linker_signature": bool(_CPP_UNDEFINED.search(log))}
    if ndk["conflicting_effective_ndk_paths"]:
        status = "NOT_EVALUATED"
        summary = "Conflicting effective NDK paths; cannot attribute a linker failure."
    elif not ndk["effective_cache_count"]:
        status = "NOT_EVALUATED"
        summary = "No effective NDK path supplied from CMakeCache; declarations alone are insufficient."
    elif ndk["effective_ndk_path_contains_whitespace"] and evidence["cpp_runtime_linker_signature"]:
        status = "SUSPECTED"
        summary = "C++ runtime linker signature and whitespace-bearing effective NDK path coexist; cause not proven."
    elif ndk["effective_ndk_path_contains_whitespace"]:
        status = "RISK_SIGNAL"
        summary = "Effective NDK path contains whitespace, but the selected linker signature is absent."
    elif evidence["cpp_runtime_linker_signature"]:
        status = "NOT_EVALUATED"
        summary = "C++ runtime linker error exists without a whitespace-bearing effective NDK path."
    else:
        status = "NO_MATCH"
        summary = "No R03 signature in the supplied evidence; this is not a build-health pass."
    return {"rule": "R03_WINDOWS_NDK_PATH", "status": status, "summary": summary, "evidence": evidence}


def _version_tuple(version: str | None) -> tuple[int, int, int] | None:
    if version is None:
        return None
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
        raise InputError("Ninja version must be numeric, such as 1.10.2")
    parts = [int(part) for part in version.split(".")]
    return tuple((parts + [0, 0])[:3])


def _r04(log: str, ninja_version: str | None, ninja_dir: str | None) -> dict:
    matches = list(_NINJA_MKDIR.finditer(log))
    log_dirs = [_winpath(match.group("directory")) for match in _NINJA_C.finditer(log)]
    unique_dirs = {str(PureWindowsPath(value)).casefold() for value in log_dirs}
    version = _version_tuple(ninja_version)
    evidence: dict = {
        "ninja_mkdir_error": bool(matches),
        "ninja_version_supplied": ninja_version,
        "ninja_version_source": "operator_argument" if ninja_version else "not_provided",
        "working_directory_source": "operator_argument" if ninja_dir else ("build_log" if log_dirs else "unresolved"),
        "longest_mkdir_path_length": None,
        "max_path_threshold": 260,
    }
    if not matches:
        return {"rule": "R04_NINJA_LONG_PATH", "status": "NO_MATCH",
                "summary": "No Ninja mkdir failure signature in the supplied log; not a build-health pass.",
                "evidence": evidence}
    if ninja_dir:
        if not re.match(r"^[A-Za-z]:[\\/]", ninja_dir):
            raise InputError("--ninja-dir must be an absolute Windows drive path")
        directory = ninja_dir
    elif len(unique_dirs) == 1:
        directory = log_dirs[0]
    else:
        return {"rule": "R04_NINJA_LONG_PATH", "status": "NOT_EVALUATED",
                "summary": "Ninja mkdir failure detected, but its working directory is unknown or conflicting.",
                "evidence": evidence}

    lengths: list[int] = []
    for match in matches[:32]:
        relative = re.sub(r"\r?\n[ \t]*", "", match.group(1)).strip()
        if not relative:
            continue
        relative = _winpath(relative)
        child = PureWindowsPath(relative)
        full = child if child.is_absolute() else PureWindowsPath(_winpath(directory)) / child
        lengths.append(len(str(full)))
    if not lengths:
        return {"rule": "R04_NINJA_LONG_PATH", "status": "NOT_EVALUATED",
                "summary": "Ninja mkdir failure captured without a parseable directory path.", "evidence": evidence}

    longest = max(lengths)
    evidence["longest_mkdir_path_length"] = longest
    evidence["ninja_version_below_1_12"] = version < (1, 12, 0) if version else None
    if longest >= 260 and version is not None and version < (1, 12, 0):
        status, summary = "SUSPECTED", "Long Ninja mkdir path and older Ninja version align with a Windows path-limit failure; causality not proven."
    elif longest >= 260:
        status, summary = "RISK_SIGNAL", "Ninja mkdir path reaches the 260-character threshold; Ninja version is unknown or not old."
    else:
        status, summary = "NOT_EVALUATED", "Ninja mkdir failure exists, but measured path does not reach the long-path threshold."
    return {"rule": "R04_NINJA_LONG_PATH", "status": status, "summary": summary, "evidence": evidence}


def diagnose(project: Path, build_log: Path, cache_paths: list[Path],
             ninja_version: str | None = None, ninja_dir: str | None = None) -> dict:
    root = project.resolve(strict=False)
    if not root.is_dir() or not (root / "android").is_dir():
        raise InputError("--project must point to a React Native project containing android/")
    if len(cache_paths) > MAX_CACHES:
        raise InputError(f"At most {MAX_CACHES} CMake cache paths may be supplied")
    log = _read_bounded(build_log, MAX_LOG_BYTES)
    ndk = _ndk_evidence(root, cache_paths)
    return {
        "schema_version": "1",
        "scope": "WINDOWS_NATIVE_LOG_TRIAGE_ONLY",
        "read_only": True,
        "findings": [_r03(log, ndk), _r04(log, ninja_version, ninja_dir)],
        "limitations": [
            "Evidence signatures are correlations, never causal proof or release certification.",
            "Effective NDK location requires a caller-supplied CMakeCache.txt; ndk.dir alone is not proof.",
            "Ninja version is operator-supplied and is not authenticated by this tool.",
            "No project executables, Gradle, CMake, Ninja, network calls, or repairs are performed.",
            "No raw machine-specific paths or log text are emitted in the report.",
        ],
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Read-only Windows native build log diagnostic (R03/R04)")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--build-log", type=Path, required=True)
    parser.add_argument("--cmake-cache", type=Path, action="append", default=[])
    parser.add_argument("--ninja-version", type=str)
    parser.add_argument("--ninja-dir", type=str)
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
        report = diagnose(args.project, args.build_log, args.cmake_cache,
                          args.ninja_version, args.ninja_dir)
    except (InputError, OSError) as exc:
        print(f"INPUT ERROR: {exc}", file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2))
    else:
        print("Nativory / Windows Native Doctor (triage only)")
        for item in report["findings"]:
            print(f"  {item['rule']}: {item['status']} - {item['summary']}")
        print("NOT VERIFIED: causal root cause, full Android build, device runtime, release readiness.")
    return 0  # Analysis completed, never 'build passed'.


if __name__ == "__main__":
    raise SystemExit(main())
