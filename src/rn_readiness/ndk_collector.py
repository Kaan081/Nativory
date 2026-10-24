"""Read-only NDK declaration discovery with explicit ownership and resolution kind."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .collector import ProjectInputError, _safe_read, project_android_root
from .ndk_models import NdkDeclaration, NdkOwnerType, NdkResolutionKind, NdkTraceResult

NDK_NUMERIC = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+\Z")
NDK_LHS = re.compile(r"(?<![.\w])ndkVersion\b")
NDK_LITERAL = re.compile(r'(?<![.\w])ndkVersion\s*(?:=\s*)?["\']([^"\']+)["\']')
NDK_INVOKE_LITERAL = re.compile(r'(?<![.\w])ndkVersion\s*\(\s*["\']([^"\']+)["\']\s*\)')
NDK_ROOT = re.compile(r"(?<![.\w])ndkVersion\s*(?:=\s*)?rootProject\.ext\.ndkVersion\b")
NDK_ROOT_PROPERTIES = re.compile(
    r'(?<![.\w])ndkVersion\s*=\s*rootProject\.properties\s*\[\s*["\']ndkVersion["\']\s*\]\.toString\s*\(\s*\)',
)
NDK_ASSIGN = re.compile(r"(?<![.\w])ndkVersion\s*(?:=\s*)?(.+)$")
NON_DECL_PREFIX = re.compile(
    r"^\s*(?:println|logger\.|ext\s*\{|val\s|def\s|var\s|subprojects\b)",
)
LOCAL_NDK_DEF = re.compile(r"^\s*(?:val|def|var)\s+ndkVersion\b")
MAP_NDK_ENTRY = re.compile(r"\[\s*ndkVersion\s*:")

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


def _mask_non_code(content: str) -> str:
    """Replace comments and string contents with spaces; preserve newlines."""
    out = list(content)
    i = 0
    n = len(content)
    state = "code"

    def blank(start: int, end: int) -> None:
        for j in range(start, end):
            if content[j] != "\n":
                out[j] = " "

    while i < n:
        ch = content[i]
        if state == "code":
            if content.startswith('"""', i):
                state = "triple_double"
                blank(i, i + 3)
                i += 3
                continue
            if content.startswith("'''", i):
                state = "triple_single"
                blank(i, i + 3)
                i += 3
                continue
            if ch == "/" and i + 1 < n and content[i + 1] == "/":
                state = "line_comment"
                blank(i, i + 2)
                i += 2
                continue
            if ch == "/" and i + 1 < n and content[i + 1] == "*":
                state = "block_comment"
                blank(i, i + 2)
                i += 2
                continue
            if ch == '"':
                state = "double"
                blank(i, i + 1)
                i += 1
                continue
            if ch == "'":
                state = "single"
                blank(i, i + 1)
                i += 1
                continue
            i += 1
            continue
        if state == "line_comment":
            if ch == "\n":
                state = "code"
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block_comment":
            if ch == "*" and i + 1 < n and content[i + 1] == "/":
                blank(i, i + 2)
                i += 2
                state = "code"
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
            continue
        if state == "double":
            if ch == "\\" and i + 1 < n:
                blank(i, i + 2)
                i += 2
                continue
            if ch == '"':
                blank(i, i + 1)
                i += 1
                state = "code"
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if state == "single":
            if ch == "\\" and i + 1 < n:
                blank(i, i + 2)
                i += 2
                continue
            if ch == "'":
                blank(i, i + 1)
                i += 1
                state = "code"
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if state == "triple_double":
            if content.startswith('"""', i):
                blank(i, i + 3)
                i += 3
                state = "code"
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if state == "triple_single":
            if content.startswith("'''", i):
                blank(i, i + 3)
                i += 3
                state = "code"
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        i += 1
    return "".join(out)


def _strip_has_property_tokens(line: str) -> str:
    return re.sub(
        r'\b(?:hasProperty|findProperty)\s*\(\s*["\']ndkVersion["\']\s*\)',
        "",
        line,
    )


def _tail_is_clean_statement_end(tail: str) -> bool:
    tail = tail.strip()
    if not tail:
        return True
    return tail[0] in ";}"


def _lhs_ndk_position(segment: str) -> int | None:
    for match in NDK_LHS.finditer(segment):
        start = match.start()
        if start > 0 and segment[start - 1] in "(.[\"'":
            continue
        return start
    return None


def _span_is_code(content: str, masked: str, start: int, end: int) -> bool:
    if start < 0 or end > len(content) or start >= end:
        return False
    for i in range(start, end):
        if masked[i] != content[i]:
            return False
    return True


def _parse_ndk_lines(
    content: str,
    *,
    owner: str,
    owner_type: NdkOwnerType,
    source: str,
) -> list[NdkDeclaration]:
    declarations: list[NdkDeclaration] = []
    masked = _mask_non_code(content)
    line_start = 0
    for raw_line in content.splitlines():
        line_end = line_start + len(raw_line)
        working_line = _strip_has_property_tokens(raw_line)
        line = working_line.strip()
        if not line or not NDK_LHS.search(line):
            line_start = line_end + 1
            continue
        if NON_DECL_PREFIX.match(line) or LOCAL_NDK_DEF.match(line) or MAP_NDK_ENTRY.search(line):
            line_start = line_end + 1
            continue

        for segment in line.split(";"):
            segment = segment.strip()
            lhs_at = _lhs_ndk_position(segment)
            if lhs_at is None:
                continue
            decl = segment[lhs_at:]
            lhs_in_working = working_line.find(segment)
            if lhs_in_working < 0:
                lhs_in_working = working_line.find("ndkVersion", 0)
            decl_offset = line_start + lhs_in_working + lhs_at
            if lhs_in_working < 0:
                decl_offset = line_start + lhs_at

            def _code_span(start: int, end: int) -> bool:
                abs_start = decl_offset + start
                abs_end = decl_offset + end
                return _span_is_code(content, masked, abs_start, abs_end)

            def _lhs_in_code(match_start: int) -> bool:
                return _code_span(match_start, match_start + len("ndkVersion"))

            match = NDK_LITERAL.search(decl) or NDK_INVOKE_LITERAL.search(decl)
            if match and not _lhs_in_code(match.start()):
                match = None
            if match:
                tail = decl[match.end():]
                if _tail_is_clean_statement_end(tail):
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

            match = NDK_ROOT_PROPERTIES.search(decl)
            if match and not _lhs_in_code(match.start()):
                match = None
            if match:
                tail = decl[match.end():]
                if _tail_is_clean_statement_end(tail):
                    declarations.append(NdkDeclaration(
                        owner=owner,
                        owner_type=owner_type,
                        source=source,
                        value=None,
                        resolution_kind=NdkResolutionKind.ROOT_INHERITED,
                        resolution_path=("ndkVersion", 'rootProject.properties["ndkVersion"].toString()'),
                    ))
                    continue

            match = NDK_ROOT.search(decl)
            if match and not _lhs_in_code(match.start()):
                match = None
            if match:
                tail = decl[match.end():]
                if _tail_is_clean_statement_end(tail):
                    declarations.append(NdkDeclaration(
                        owner=owner,
                        owner_type=owner_type,
                        source=source,
                        value=None,
                        resolution_kind=NdkResolutionKind.ROOT_INHERITED,
                        resolution_path=("ndkVersion", "rootProject.ext.ndkVersion"),
                    ))
                    continue

            assign = NDK_ASSIGN.search(decl)
            if assign and not _lhs_in_code(assign.start()):
                assign = None
            if not assign:
                continue
            expr = assign.group(1).strip().rstrip("}")
            if not expr:
                continue
            if re.fullmatch(r'["\'][^"\']+["\'](?:\s*[;}]|\s*)', expr):
                continue
            if expr == "rootProject.ext.ndkVersion":
                continue
            if NDK_ROOT_PROPERTIES.fullmatch(f"ndkVersion = {expr}"):
                continue
            declarations.append(NdkDeclaration(
                owner=owner,
                owner_type=owner_type,
                source=source,
                value=None,
                resolution_kind=NdkResolutionKind.UNSUPPORTED_EXPRESSION,
                resolution_path=("ndkVersion", expr),
            ))
        line_start = line_end + 1
    return declarations


def _ndk_relative_source(repo: Path, path: Path) -> str | None:
    try:
        return path.resolve(strict=False).relative_to(repo.resolve(strict=False)).as_posix()
    except (OSError, ValueError):
        return None


def _scan_gradle_file(
    repo: Path,
    gradle_path: Path,
    *,
    owner: str,
    owner_type: NdkOwnerType,
) -> list[NdkDeclaration]:
    rel = _ndk_relative_source(repo, gradle_path)
    if rel is None:
        return []
    try:
        content = _safe_read(gradle_path)
    except OSError:
        return []
    if content is None:
        return []
    if "ndkVersion" not in content:
        return []
    return _parse_ndk_lines(content, owner=owner, owner_type=owner_type, source=rel)


def _package_name(package_root: Path) -> str | None:
    manifest = package_root / "package.json"
    try:
        content = _safe_read(manifest)
    except OSError:
        return None
    if content is None:
        return None
    if content.startswith("\ufeff"):
        content = content[1:]
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    return name if isinstance(name, str) and name.strip() else None


def _resolved_within(resolved: Path, root: Path) -> bool:
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
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
            resolved_dir = directory.resolve(strict=False)
        except OSError:
            return
        if not _resolved_within(resolved_dir, root):
            return
        try:
            with os.scandir(resolved_dir) as scan:
                entries = sorted(scan, key=lambda item: item.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            name = entry.name
            try:
                resolved_entry = Path(entry.path).resolve(strict=False)
            except OSError:
                continue
            if not _resolved_within(resolved_entry, root):
                continue
            if entry.is_file(follow_symlinks=False):
                if name in GRADLE_FILE_NAMES:
                    found.append(resolved_entry)
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            if name in PACKAGE_GRADLE_PRUNE_DIRS or name.startswith("."):
                continue
            walk(resolved_entry, depth + 1)

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
        gradle_path = project / relname
        if _ndk_relative_source(repo, gradle_path) is None:
            continue
        declarations.extend(_scan_gradle_file(
            repo,
            gradle_path,
            owner=owner,
            owner_type=NdkOwnerType.PROJECT,
        ))
    return declarations


def _collect_dependency_declarations(repo: Path, project: Path) -> list[NdkDeclaration]:
    declarations: list[NdkDeclaration] = []
    seen_sources: set[str] = set()
    node_modules = repo / "node_modules"
    for package_root in _iter_installed_packages(node_modules):
        gradle_paths = _discover_package_gradle_files(package_root)
        if not gradle_paths:
            continue
        owner = _package_name(package_root)
        if owner is None:
            continue
        for gradle_path in gradle_paths:
            rel = _ndk_relative_source(repo, gradle_path)
            if rel is None or rel in seen_sources:
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
