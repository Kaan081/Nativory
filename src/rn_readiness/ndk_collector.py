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
NON_DECL_PREFIX = re.compile(r"^\s*(?:println|logger\.|subprojects\b)")
MAP_NDK_ENTRY = re.compile(r"\[\s*ndkVersion\s*:")
HAS_PROPERTY_TOKEN = re.compile(
    r'\b(?:hasProperty|findProperty)\s*\(\s*["\']ndkVersion["\']\s*\)',
)
LOCAL_BINDING_WORD = re.compile(
    r"\b(?:val|var|def|final|const|static|public|private|protected|lateinit)\b",
)
COMMAND_CALLEE = re.compile(r"^([A-Za-z_]\w*)(?:\s|\(|$)")
CONTINUATION_LINE = re.compile(r"^\s*(?:\?\?|\?\:|&&|\|\||\.|\?\.|[+\-*/?:])")

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
FIXTURE_SOURCE_PARTS = frozenset({
    "example", "examples", "sample", "samples", "demo", "demos", "test", "tests",
})


def _declaration_sort_key(item: NdkDeclaration) -> tuple[str, str, str, str, str]:
    return (
        item.owner,
        item.owner_type.value,
        item.source,
        item.resolution_kind.value,
        item.value or "",
    )


def _mask_non_code(content: str, *, nested_block_comments: bool = False) -> str:
    """Replace comments and string contents with spaces; preserve newlines."""
    out = list(content)
    i = 0
    n = len(content)
    state = "code"
    block_depth = 0

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
                block_depth = 1
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
            if nested_block_comments and ch == "/" and i + 1 < n and content[i + 1] == "*":
                blank(i, i + 2)
                block_depth += 1
                i += 2
                continue
            if ch == "*" and i + 1 < n and content[i + 1] == "/":
                blank(i, i + 2)
                i += 2
                if nested_block_comments:
                    block_depth -= 1
                    if block_depth > 0:
                        continue
                state = "code"
                block_depth = 0
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
            continue
        if state == "double":
            if ch == "\n":
                state = "code"
                i += 1
                continue
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
            if ch == "\n":
                state = "code"
                i += 1
                continue
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


def _pad_has_property_tokens(line: str) -> str:
    return HAS_PROPERTY_TOKEN.sub(lambda match: " " * (match.end() - match.start()), line)


def _tail_is_clean_statement_end(tail: str) -> bool:
    tail = tail.strip()
    if not tail:
        return True
    return tail[0] in ";}"


def _lhs_ndk_position(segment: str) -> int | None:
    for match in NDK_LHS.finditer(segment):
        start = match.start()
        if start > 0 and segment[start - 1] in "(.[\"',:":
            continue
        return start
    return None


def _statement_boundary_start(segment: str, lhs_at: int) -> int:
    start = 0
    for index in range(lhs_at):
        if segment[index] in "{;":
            start = index + 1
        elif segment[index] == ")":
            start = index + 1
    return start


def _prefix_allows_dsl_lhs(segment: str, lhs_at: int) -> bool:
    prefix = segment[_statement_boundary_start(segment, lhs_at):lhs_at]
    if not prefix.strip():
        return True
    if LOCAL_BINDING_WORD.search(prefix):
        return False
    if re.search(r"[\w.\]>]", prefix):
        return False
    return True


def _following_dsl_shape(segment: str, lhs_at: int) -> str:
    after = segment[lhs_at + len("ndkVersion"):].lstrip()
    if not after:
        return "none"
    if after[0] == ":":
        return "none"
    if re.match(r"(?:==|!=|\+=|-=|\*=|/=|%=|\?=|<=|>=)", after):
        return "none"
    if after.startswith("="):
        return "assign"
    if after[0] in '"\'':
        return "literal"
    if after.startswith("("):
        return "invoke"
    if re.match(r"^rootProject\.", after):
        return "command"
    callee = COMMAND_CALLEE.match(after)
    if not callee:
        return "none"
    if callee.group(1) == "to":
        return "none"
    return "command"


def _eligible_dsl_lhs(segment: str, lhs_at: int) -> str:
    if not _prefix_allows_dsl_lhs(segment, lhs_at):
        return "none"
    return _following_dsl_shape(segment, lhs_at)


def _next_code_line_starts_with_continuation(
    content: str,
    masked: str,
    line_end: int,
) -> bool:
    position = line_end
    while position < len(content) and content[position] in "\r\n":
        position += 1
    if position >= len(content):
        return False
    next_end = content.find("\n", position)
    if next_end == -1:
        next_line = content[position:]
        masked_line = masked[position:]
    else:
        next_line = content[position:next_end]
        masked_line = masked[position:next_end]
    for index, character in enumerate(next_line):
        if character.strip() == "":
            continue
        if masked_line[index] != character:
            continue
        return CONTINUATION_LINE.match(next_line[index:]) is not None
    return False


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
    nested_comments = source.endswith(".kts")
    masked = _mask_non_code(content, nested_block_comments=nested_comments)
    line_start = 0
    for raw_line in content.splitlines():
        line_end = line_start + len(raw_line)
        working_line = _pad_has_property_tokens(raw_line)
        if not working_line.strip() or not NDK_LHS.search(working_line):
            line_start = line_end + 1
            continue
        if NON_DECL_PREFIX.match(working_line.strip()) or MAP_NDK_ENTRY.search(working_line):
            line_start = line_end + 1
            continue

        search_from = 0
        for segment in working_line.strip().split(";"):
            segment = segment.strip()
            if not segment:
                continue
            lhs_at = _lhs_ndk_position(segment)
            if lhs_at is None:
                continue
            dsl_shape = _eligible_dsl_lhs(segment, lhs_at)
            if dsl_shape == "none":
                continue
            decl = segment[lhs_at:]
            seg_offset = working_line.find(segment, search_from)
            if seg_offset < 0:
                seg_offset = working_line.find("ndkVersion", search_from)
            if seg_offset < 0:
                continue
            search_from = seg_offset + max(len(segment), 1)
            decl_base = line_start + seg_offset + lhs_at
            decl_masked = masked[decl_base:decl_base + len(decl)]

            def _lhs_in_code(match_start: int) -> bool:
                abs_start = decl_base + match_start
                abs_end = abs_start + len("ndkVersion")
                return _span_is_code(content, masked, abs_start, abs_end)

            def _tail_ok(match_end: int) -> bool:
                return _tail_is_clean_statement_end(decl_masked[match_end:])

            def _continued_after_line() -> bool:
                return _next_code_line_starts_with_continuation(content, masked, line_end)

            def _append_continued() -> None:
                declarations.append(NdkDeclaration(
                    owner=owner,
                    owner_type=owner_type,
                    source=source,
                    value=None,
                    resolution_kind=NdkResolutionKind.UNSUPPORTED_EXPRESSION,
                    resolution_path=("ndkVersion", "continued_expression"),
                ))

            def _append_literal(match: re.Match[str]) -> None:
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

            handled = False
            if dsl_shape in ("literal", "invoke", "assign", "command"):
                match = NDK_LITERAL.search(decl) or NDK_INVOKE_LITERAL.search(decl)
                if match and not _lhs_in_code(match.start()):
                    match = None
                if match and _tail_ok(match.end()):
                    if _continued_after_line():
                        _append_continued()
                    else:
                        _append_literal(match)
                    handled = True

            if not handled and dsl_shape in ("assign", "command"):
                match = NDK_ROOT_PROPERTIES.search(decl)
                if match and not _lhs_in_code(match.start()):
                    match = None
                if match and _tail_ok(match.end()):
                    if _continued_after_line():
                        _append_continued()
                    else:
                        declarations.append(NdkDeclaration(
                            owner=owner,
                            owner_type=owner_type,
                            source=source,
                            value=None,
                            resolution_kind=NdkResolutionKind.ROOT_INHERITED,
                            resolution_path=("ndkVersion", 'rootProject.properties["ndkVersion"].toString()'),
                        ))
                    handled = True

            if not handled and dsl_shape in ("assign", "command"):
                match = NDK_ROOT.search(decl)
                if match and not _lhs_in_code(match.start()):
                    match = None
                if match and _tail_ok(match.end()):
                    if _continued_after_line():
                        _append_continued()
                    else:
                        declarations.append(NdkDeclaration(
                            owner=owner,
                            owner_type=owner_type,
                            source=source,
                            value=None,
                            resolution_kind=NdkResolutionKind.ROOT_INHERITED,
                            resolution_path=("ndkVersion", "rootProject.ext.ndkVersion"),
                        ))
                    handled = True

            if not handled and dsl_shape in ("literal", "invoke", "assign", "command"):
                assign = NDK_ASSIGN.search(decl)
                if assign and not _lhs_in_code(assign.start()):
                    assign = None
                if assign:
                    if _continued_after_line():
                        _append_continued()
                    else:
                        expr = decl_masked[assign.start(1):assign.end(1)].strip().rstrip("}")
                        if expr and not re.fullmatch(
                            r'["\'][^"\']+["\'](?:\s*[;}]|\s*)',
                            expr,
                        ):
                            if expr not in (
                                "rootProject.ext.ndkVersion",
                            ) and not NDK_ROOT_PROPERTIES.fullmatch(f"ndkVersion = {expr}"):
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


def _resolved_node_modules_in_repo(repo: Path) -> Path | None:
    try:
        repo_resolved = repo.resolve(strict=False)
        nm_resolved = (repo / "node_modules").resolve(strict=False)
        nm_resolved.relative_to(repo_resolved)
    except (OSError, ValueError):
        return None
    return nm_resolved


def _discover_package_gradle_files(package_root: Path, nm_boundary: Path) -> list[Path]:
    try:
        root = package_root.resolve(strict=False)
    except OSError:
        return []
    if not _resolved_within(root, nm_boundary):
        return []
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > PACKAGE_GRADLE_MAX_DEPTH:
            return
        try:
            resolved_dir = directory.resolve(strict=False)
        except OSError:
            return
        if not _resolved_within(resolved_dir, nm_boundary):
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
            if not _resolved_within(resolved_entry, nm_boundary):
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
    try:
        return sorted(found, key=lambda path: path.relative_to(root).as_posix().lower())
    except ValueError:
        return []


def _iter_installed_packages(node_modules: Path, nm_boundary: Path) -> list[Path]:
    if not node_modules.is_dir():
        return []
    try:
        if not _resolved_within(node_modules.resolve(strict=False), nm_boundary):
            return []
    except OSError:
        return []
    packages: list[Path] = []
    for entry in sorted(node_modules.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_symlink():
            continue
        try:
            resolved = entry.resolve(strict=False)
        except OSError:
            continue
        if not _resolved_within(resolved, nm_boundary):
            continue
        if entry.name.startswith("@"):
            if not entry.is_dir():
                continue
            for scoped in sorted(entry.iterdir(), key=lambda item: item.name.lower()):
                if not scoped.is_dir() or scoped.is_symlink():
                    continue
                try:
                    scoped_resolved = scoped.resolve(strict=False)
                except OSError:
                    continue
                if _resolved_within(scoped_resolved, nm_boundary):
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
    nm_boundary = _resolved_node_modules_in_repo(repo)
    if nm_boundary is None:
        return []
    node_modules = repo / "node_modules"
    for package_root in _iter_installed_packages(node_modules, nm_boundary):
        try:
            if not _resolved_within(package_root.resolve(strict=False), nm_boundary):
                continue
        except OSError:
            continue
        gradle_paths = _discover_package_gradle_files(package_root, nm_boundary)
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


def _is_fixture_dependency_source(source: str) -> bool:
    return any(part.lower() in FIXTURE_SOURCE_PARTS for part in source.split("/"))


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
        if _is_fixture_dependency_source(item.source):
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
