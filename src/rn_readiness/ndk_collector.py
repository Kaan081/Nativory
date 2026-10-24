"""Read-only NDK declaration discovery with explicit ownership and resolution kind."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .collector import ProjectInputError, _relative_source, _safe_read, project_android_root
from .ndk_models import NdkDeclaration, NdkOwnerType, NdkResolutionKind, NdkTraceResult

NDK_NUMERIC = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+\Z")
NDK_LITERAL = re.compile(r'\bndkVersion\s*(?:=\s*)?["\']([^"\']+)["\']')
NDK_INVOKE_LITERAL = re.compile(r'\bndkVersion\s*\(\s*["\']([^"\']+)["\']\s*\)')
NDK_ROOT = re.compile(r"\bndkVersion\s*(?:=\s*)?rootProject\.ext\.ndkVersion\b")
NDK_ROOT_PROPERTIES = re.compile(
    r"\bndkVersion\s*=\s*rootProject\.properties\s*\[\s*[\"']ndkVersion[\"']\s*\]\.toString\s*\(\s*\)",
)
NDK_ASSIGN = re.compile(r"\bndkVersion\s*(?:=\s*)?(.+?)(?:\s*$|\s*//|\s*\})")
SPURIOUS_NDK_CONTEXT = re.compile(
    r'\b(?:hasProperty|findProperty)\s*\(\s*["\']ndkVersion["\']',
)

PROJECT_GRADLE_FILES = (
    "build.gradle",
    "build.gradle.kts",
    "app/build.gradle",
    "app/build.gradle.kts",
)
PACKAGE_GRADLE_MAX_DEPTH = 16
PACKAGE_GRADLE_PRUNE_DIRS = frozenset({"node_modules", "build", ".gradle"})
GRADLE_FILE_NAMES = frozenset({"build.gradle", "build.gradle.kts"})

ATTENTION_LITERAL_DIFF = "dependency_literal_pin_differs_from_project"


def _declaration_sort_key(item: NdkDeclaration) -> tuple[str, str, str, str, str]:
    return (
        item.owner,
        item.owner_type.value,
        item.source,
        item.resolution_kind.value,
        item.value or "",
    )


def _strip_ndk_source(content: str) -> str:
    """Line comments only; block-comment stripping false-matches on Gradle `**/*` globs."""
    return "\n".join(line.split("//", 1)[0] for line in content.splitlines())


def _is_spurious_ndk_line(line: str) -> bool:
    return SPURIOUS_NDK_CONTEXT.search(line) is not None


def _index_in_string_literal(line: str, index: int) -> bool:
    in_single = False
    in_double = False
    escape = False
    for i, ch in enumerate(line):
        if i >= index:
            return in_single or in_double
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
    return in_single or in_double


def _search_outside_strings(pattern: re.Pattern[str], line: str) -> re.Match[str] | None:
    for match in pattern.finditer(line):
        if not _index_in_string_literal(line, match.start()):
            return match
    return None


def _parse_ndk_lines(
    content: str,
    *,
    owner: str,
    owner_type: NdkOwnerType,
    source: str,
) -> list[NdkDeclaration]:
    declarations: list[NdkDeclaration] = []
    text = _strip_ndk_source(content)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or "ndkVersion" not in line:
            continue
        if _is_spurious_ndk_line(line):
            continue
        match = _search_outside_strings(NDK_LITERAL, line) or _search_outside_strings(NDK_INVOKE_LITERAL, line)
        if match:
            value = match.group(1)
            kind = NdkResolutionKind.LITERAL
            if not NDK_NUMERIC.fullmatch(value):
                kind = NdkResolutionKind.UNSUPPORTED_EXPRESSION
                value = None
            declarations.append(NdkDeclaration(
                owner=owner,
                owner_type=owner_type,
                source=source,
                value=value if kind is NdkResolutionKind.LITERAL else None,
                resolution_kind=kind,
                resolution_path=("ndkVersion", "literal"),
            ))
            continue

        if _search_outside_strings(NDK_ROOT, line):
            declarations.append(NdkDeclaration(
                owner=owner,
                owner_type=owner_type,
                source=source,
                value=None,
                resolution_kind=NdkResolutionKind.ROOT_INHERITED,
                resolution_path=("ndkVersion", "rootProject.ext.ndkVersion"),
            ))
            continue

        if _search_outside_strings(NDK_ROOT_PROPERTIES, line):
            declarations.append(NdkDeclaration(
                owner=owner,
                owner_type=owner_type,
                source=source,
                value=None,
                resolution_kind=NdkResolutionKind.ROOT_INHERITED,
                resolution_path=("ndkVersion", 'rootProject.properties["ndkVersion"].toString()'),
            ))
            continue

        assign = _search_outside_strings(NDK_ASSIGN, line)
        if assign and assign.group(1).strip():
            expr = assign.group(1).strip().rstrip("}")
            if expr.startswith('"') or expr.startswith("'"):
                continue
            if expr == "rootProject.ext.ndkVersion":
                continue
            if NDK_ROOT_PROPERTIES.search(expr):
                continue
            declarations.append(NdkDeclaration(
                owner=owner,
                owner_type=owner_type,
                source=source,
                value=None,
                resolution_kind=NdkResolutionKind.UNSUPPORTED_EXPRESSION,
                resolution_path=("ndkVersion", expr),
            ))
    return declarations


def _scan_gradle_file(
    repo: Path,
    gradle_path: Path,
    *,
    owner: str,
    owner_type: NdkOwnerType,
) -> list[NdkDeclaration]:
    rel = _relative_source(repo, gradle_path)
    try:
        content = _safe_read(gradle_path)
    except OSError:
        return []
    if content is None:
        return []
    if "ndkVersion" not in content:
        return []
    return _parse_ndk_lines(content, owner=owner, owner_type=owner_type, source=rel)


def _node_modules_bases(repo: Path, project: Path) -> list[Path]:
    bases: list[Path] = []
    for base in (repo, project.parent):
        try:
            normalized = base.resolve(strict=False)
        except OSError:
            continue
        if normalized not in bases:
            bases.append(normalized)
    return bases


def _package_name(package_root: Path) -> str | None:
    manifest = package_root / "package.json"
    try:
        content = _safe_read(manifest)
    except OSError:
        return None
    if content is None:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    name = data.get("name")
    return name if isinstance(name, str) and name.strip() else None


def _package_shallow_gradle_marker(package_root: Path) -> bool:
    """Cheap gate before deep Gradle discovery (no semver-specific paths)."""
    try:
        root = package_root.resolve(strict=False)
    except OSError:
        return False
    for name in GRADLE_FILE_NAMES:
        candidate = root / name
        if candidate.is_file() and not candidate.is_symlink():
            return True
    android = root / "android"
    if android.is_dir() and not android.is_symlink():
        for name in GRADLE_FILE_NAMES:
            candidate = android / name
            if candidate.is_file() and not candidate.is_symlink():
                return True
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return False
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            continue
        if entry.name in PACKAGE_GRADLE_PRUNE_DIRS or entry.name.startswith("."):
            continue
        for name in GRADLE_FILE_NAMES:
            candidate = entry / name
            if candidate.is_file() and not candidate.is_symlink():
                return True
        nested_android = entry / "android"
        if nested_android.is_dir() and not nested_android.is_symlink():
            for name in GRADLE_FILE_NAMES:
                candidate = nested_android / name
                if candidate.is_file() and not candidate.is_symlink():
                    return True
    return False


def _discover_package_gradle_files(package_root: Path) -> list[Path]:
    try:
        root = package_root.resolve(strict=False)
    except OSError:
        return []
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > PACKAGE_GRADLE_MAX_DEPTH:
            return
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda item: item.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            name = entry.name
            if entry.is_file(follow_symlinks=False):
                if name in GRADLE_FILE_NAMES:
                    found.append(Path(entry.path))
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            if name in PACKAGE_GRADLE_PRUNE_DIRS or name.startswith("."):
                continue
            walk(Path(entry.path), depth + 1)

    walk(root, 0)
    return sorted(found, key=lambda path: path.relative_to(root).as_posix().lower())


def _iter_installed_packages(node_modules: Path) -> list[Path]:
    if not node_modules.is_dir() or node_modules.is_symlink():
        return []
    packages: list[Path] = []
    for entry in sorted(node_modules.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith(".") or entry.is_symlink():
            continue
        if entry.name.startswith("@"):
            if not entry.is_dir():
                continue
            for scoped in sorted(entry.iterdir(), key=lambda item: item.name.lower()):
                if scoped.is_dir() and not scoped.is_symlink():
                    packages.append(scoped)
            continue
        if entry.is_dir():
            packages.append(entry)
    return packages


def _collect_project_declarations(repo: Path, project: Path) -> list[NdkDeclaration]:
    owner = "project"
    declarations: list[NdkDeclaration] = []
    for relname in PROJECT_GRADLE_FILES:
        declarations.extend(_scan_gradle_file(
            repo,
            project / relname,
            owner=owner,
            owner_type=NdkOwnerType.PROJECT,
        ))
    return declarations


def _collect_dependency_declarations(repo: Path, project: Path) -> list[NdkDeclaration]:
    declarations: list[NdkDeclaration] = []
    seen_sources: set[str] = set()
    for base in _node_modules_bases(repo, project):
        node_modules = base / "node_modules"
        for package_root in _iter_installed_packages(node_modules):
            if not _package_shallow_gradle_marker(package_root):
                continue
            gradle_paths = _discover_package_gradle_files(package_root)
            if not gradle_paths:
                continue
            owner = _package_name(package_root)
            if owner is None:
                continue
            for gradle_path in gradle_paths:
                rel = _relative_source(repo, gradle_path)
                if rel in seen_sources:
                    continue
                seen_sources.add(rel)
                declarations.extend(_scan_gradle_file(
                    repo,
                    gradle_path,
                    owner=owner,
                    owner_type=NdkOwnerType.INSTALLED_DEPENDENCY,
                ))
    return declarations


def _attention_signals(declarations: list[NdkDeclaration]) -> list[str]:
    project_literals = sorted({
        item.value
        for item in declarations
        if item.owner_type is NdkOwnerType.PROJECT
        and item.resolution_kind is NdkResolutionKind.LITERAL
        and item.value is not None
    })
    if len(project_literals) != 1:
        return []
    project_value = project_literals[0]
    signals: list[str] = []
    for item in declarations:
        if item.owner_type is not NdkOwnerType.INSTALLED_DEPENDENCY:
            continue
        if item.resolution_kind is not NdkResolutionKind.LITERAL or item.value is None:
            continue
        if item.value != project_value and ATTENTION_LITERAL_DIFF not in signals:
            signals.append(ATTENTION_LITERAL_DIFF)
    return signals


def trace_ndk(path: str | Path) -> NdkTraceResult:
    repo = Path(path).expanduser().resolve()
    if not repo.is_dir():
        raise ProjectInputError(f"Not an accessible directory: {path}")
    project = project_android_root(repo)
    declarations = _collect_project_declarations(repo, project)
    declarations.extend(_collect_dependency_declarations(repo, project))
    unique = {item: None for item in declarations}
    ordered = tuple(sorted(unique, key=_declaration_sort_key))
    return NdkTraceResult(ordered, tuple(_attention_signals(list(ordered))))
