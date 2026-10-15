"""Evidence discovery for the deliberately narrow R02 spike.

No Gradle execution, shell, arbitrary expression evaluation, or generic Gradle parsing.
The collector recognizes a small set of explicit AGP declarations plus the modern
React Native Gradle Plugin includeBuild -> local package -> version catalog path.
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import Evidence, EvidenceScope, ResolvedFact, ResolutionStatus

MAX_FILE_BYTES = 1_000_000
VERSION = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){1,2}\Z")
WRAPPER_VERSION = re.compile(r"(?:^|/)gradle-([0-9][0-9A-Za-z.+-]*)-(?:bin|all)\.zip\Z")
PLUGIN_VERSION = re.compile(
    r"(?:^|[{};])\s*id\s*(?:\(\s*['\"]com\.android\.(?:application|library)['\"]\s*\)"
    r"|\s+['\"]com\.android\.(?:application|library)['\"])"
    r"\s+version\s*(?:\(\s*)?['\"]([^'\"]+)['\"]", re.MULTILINE
)
CLASSPATH_VERSION = re.compile(
    r"(?:^|[{};])\s*classpath\s*(?:\(\s*)?['\"]com\.android\.tools\.build:gradle:([0-9A-Za-z.+_-]+)['\"]",
    re.MULTILINE,
)
UNVERSIONED_CLASSPATH = re.compile(
    r"(?:^|[{};])\s*classpath\s*(?:\(\s*)?['\"]com\.android\.tools\.build:gradle['\"]",
    re.MULTILINE,
)
ANDROID_ALIAS = re.compile(r"\balias\s*\(\s*libs\.plugins\.[A-Za-z_][A-Za-z0-9_.]*\s*\)")
ANDROID_ID = re.compile(
    r"(?:^|[{};])\s*id\s*(?:\(\s*['\"]com\.android\.(?:application|library)['\"]\s*\)"
    r"|\s+['\"]com\.android\.(?:application|library)['\"])",
    re.MULTILINE,
)
RN_INCLUDE_BUILD = re.compile(
    r"\bincludeBuild\s*\(\s*['\"]([^'\"]*@react-native/gradle-plugin[^'\"]*)['\"]\s*\)"
)
RN_DYNAMIC_REQUIRE = re.compile(
    r"require\.resolve\(\s*['\"]@react-native/gradle-plugin/package\.json['\"]\s*,\s*"
    r"\{\s*paths\s*:\s*\[\s*require\.resolve\(\s*['\"]react-native/package\.json['\"]\s*\)"
    r"\s*\]\s*\}\s*\)",
    re.DOTALL,
)
TOML_SECTION = re.compile(r"^\s*\[([^]]+)]\s*$")
TOML_AGP = re.compile(r'^\s*agp\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$')


class ProjectInputError(ValueError):
    """A supplied project path is invalid (not a domain UNKNOWN)."""


def _safe_read(path: Path) -> str | None:
    """Return None for an absent file. Raise OSError for unsafe/unreadable files."""
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or path.resolve() != path.absolute():
        raise OSError("Symlink/redirected configuration file is unsupported")
    if not path.is_file():
        raise OSError("Expected a regular file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise OSError("Configuration file exceeds 1 MB scan limit")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise OSError(str(error)) from error


def _strip_comments(content: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def project_android_root(repo: Path) -> Path:
    android = repo / "android"
    if any((android / marker).exists() for marker in (
        "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"
    )) or (android / "gradle/wrapper/gradle-wrapper.properties").exists():
        return android
    return repo


def _relative_source(repo: Path, path: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def _evidence_sort_key(item: Evidence) -> tuple[str, str, str, tuple[str, ...]]:
    return (item.source, item.scope.value, item.value or "", item.resolution_path)


def _resolved_fact(component: str, evidence: list[Evidence], *,
                   hazard: ResolutionStatus | None = None) -> ResolvedFact:
    unique = {item: None for item in evidence}
    ordered = tuple(sorted(unique, key=_evidence_sort_key))
    if hazard is not None:
        return ResolvedFact(component, None, hazard, ordered)
    values = sorted({item.value for item in ordered if item.value is not None})
    if len(values) > 1:
        return ResolvedFact(component, None, ResolutionStatus.CONFLICTING_EVIDENCE, ordered)
    if len(values) == 1:
        return ResolvedFact(component, values[0], ResolutionStatus.RESOLVED, ordered)
    return ResolvedFact(component, None, ResolutionStatus.NO_EVIDENCE, ordered)


def collect_gradle(repo: Path, project: Path) -> ResolvedFact:
    filename = project / "gradle/wrapper/gradle-wrapper.properties"
    rel = _relative_source(repo, filename)
    try:
        content = _safe_read(filename)
    except OSError:
        return ResolvedFact(
            "gradle", None, ResolutionStatus.MALFORMED_EVIDENCE,
            (Evidence(None, EvidenceScope.DECLARED, rel, ("gradle wrapper",)),),
        )
    if content is None:
        return ResolvedFact("gradle", None, ResolutionStatus.NO_EVIDENCE)

    urls: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith(("#", "!")) or not line:
            continue
        match = re.match(r"distributionUrl\s*[=:]\s*(.+)$", line)
        if match:
            urls.append(match.group(1).strip().replace("\\:", ":"))
    if not urls:
        return ResolvedFact(
            "gradle", None, ResolutionStatus.NO_EVIDENCE,
            (Evidence(None, EvidenceScope.DECLARED, rel, ("gradle wrapper", "distributionUrl absent")),),
        )

    evidence: list[Evidence] = []
    for url in urls:
        match = WRAPPER_VERSION.search(url)
        if match is None:
            evidence.append(Evidence(None, EvidenceScope.DECLARED, rel, ("gradle wrapper", "distributionUrl")))
            return ResolvedFact("gradle", None, ResolutionStatus.UNSUPPORTED_LAYOUT, tuple(evidence))
        version = match.group(1)
        evidence.append(Evidence(version, EvidenceScope.DECLARED, rel, ("gradle wrapper", "distributionUrl")))
        if not VERSION.fullmatch(version):
            return ResolvedFact("gradle", None, ResolutionStatus.MALFORMED_EVIDENCE, tuple(evidence))
    return _resolved_fact("gradle", evidence)


def _parse_plugin_catalog(
    repo: Path, plugin_root: Path, *, entry_step: str = "android/settings.gradle includeBuild"
) -> tuple[Evidence | None, ResolutionStatus | None]:
    catalog = plugin_root / "gradle/libs.versions.toml"
    source = _relative_source(repo, catalog)
    path = (entry_step, "@react-native/gradle-plugin", "gradle/libs.versions.toml")
    try:
        content = _safe_read(catalog)
    except OSError:
        return Evidence(None, EvidenceScope.LOCAL_DEPENDENCY, source, path), ResolutionStatus.MALFORMED_EVIDENCE
    if content is None:
        return Evidence(None, EvidenceScope.LOCAL_DEPENDENCY, source, path), ResolutionStatus.MALFORMED_EVIDENCE

    section: str | None = None
    values: list[str] = []
    for raw in content.splitlines():
        match = TOML_SECTION.match(raw)
        if match:
            section = match.group(1).strip()
            continue
        if section != "versions":
            continue
        agp = TOML_AGP.match(raw)
        if agp:
            values.append(agp.group(1))
    if len(values) != 1 or not VERSION.fullmatch(values[0]):
        value = values[0] if len(values) == 1 else None
        return Evidence(value, EvidenceScope.LOCAL_DEPENDENCY, source, path), ResolutionStatus.MALFORMED_EVIDENCE
    return Evidence(values[0], EvidenceScope.LOCAL_DEPENDENCY, source, path), None


def _dynamic_rn_include_detected(text: str) -> bool:
    """Recognize only the two source-backed dynamic RN includeBuild shapes in scope.

    This does not execute Node or Gradle. It proves only that settings.gradle wires the
    RN Gradle Plugin through the specific require.resolve(package.json, paths=[...])
    expression used by observed production React Native apps.
    """
    for match in RN_DYNAMIC_REQUIRE.finditer(text):
        # MetaMask-style inline form: includeBuild(new File([..., require.resolve(...) ...]))
        before = text[max(0, match.start() - 700):match.start()]
        include_pos = before.rfind("includeBuild")
        if include_pos >= 0:
            segment = before[include_pos:]
            if re.search(r"\bincludeBuild\s*\(\s*new\s+File\s*\(", segment):
                return True

        # Mattermost-style variable form: def plugin = new File(...require.resolve...)
        # followed by includeBuild(plugin). Keep this deliberately narrow.
        prefix = text[max(0, match.start() - 1600):match.start()]
        definitions = list(re.finditer(
            r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*new\s+File\s*\(", prefix
        ))
        if definitions:
            variable = definitions[-1].group(1)
            after = text[match.end():match.end() + 2200]
            if re.search(rf"\bincludeBuild\s*\(\s*{re.escape(variable)}\s*\)", after):
                return True
    return False


def _dynamic_local_plugin_root(repo: Path, project: Path) -> tuple[Path | None, ResolutionStatus | None]:
    """Locate a conventional installed RN plugin without executing require.resolve.

    We support only a single unambiguous local node_modules installation adjacent to
    the scanned app root. Multiple plausible installations remain unsupported rather
    than guessing Node's package-resolution precedence.
    """
    bases: list[Path] = []
    for base in (repo, project.parent):
        try:
            normalized = base.resolve(strict=False)
        except OSError:
            return None, ResolutionStatus.MALFORMED_EVIDENCE
        if normalized not in bases:
            bases.append(normalized)

    installed: list[Path] = []
    for base in bases:
        node_modules = base / "node_modules"
        plugin_root = node_modules / "@react-native/gradle-plugin"
        react_native_package = node_modules / "react-native/package.json"
        if plugin_root.is_symlink() or react_native_package.is_symlink():
            if plugin_root.exists() or react_native_package.exists():
                return None, ResolutionStatus.UNSUPPORTED_LAYOUT
        if plugin_root.is_dir() and react_native_package.is_file():
            try:
                normalized = plugin_root.resolve(strict=False)
            except OSError:
                return None, ResolutionStatus.MALFORMED_EVIDENCE
            if normalized not in installed:
                installed.append(normalized)

    if len(installed) > 1:
        return None, ResolutionStatus.UNSUPPORTED_LAYOUT
    if len(installed) == 1:
        return installed[0], None
    return None, ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED


def _discover_rn_local_dependency(repo: Path, project: Path) -> tuple[list[Evidence], ResolutionStatus | None, bool]:
    evidence: list[Evidence] = []
    include_paths: list[tuple[Path, str, str]] = []
    literal_seen = False
    dynamic_seen = False

    for relname in ("settings.gradle", "settings.gradle.kts"):
        settings = project / relname
        rel = _relative_source(repo, settings)
        try:
            content = _safe_read(settings)
        except OSError:
            return evidence, ResolutionStatus.MALFORMED_EVIDENCE, True
        if content is None:
            continue
        text = _strip_comments(content)

        for match in RN_INCLUDE_BUILD.finditer(text):
            literal_seen = True
            raw_path = match.group(1)
            evidence.append(Evidence(
                None,
                EvidenceScope.DECLARED,
                rel,
                ("android/settings.gradle includeBuild", "@react-native/gradle-plugin"),
            ))
            if "$" in raw_path or "{" in raw_path or "}" in raw_path:
                return evidence, ResolutionStatus.UNSUPPORTED_LAYOUT, True
            include_paths.append((settings.parent / raw_path, rel, raw_path))

        if _dynamic_rn_include_detected(text):
            dynamic_seen = True
            evidence.append(Evidence(
                None,
                EvidenceScope.DECLARED,
                rel,
                (
                    "android/settings.gradle dynamic require.resolve includeBuild",
                    "@react-native/gradle-plugin",
                ),
            ))

    if not literal_seen and not dynamic_seen:
        return evidence, None, False

    # Mixed literal + dynamic ownership is intentionally not assigned precedence.
    if literal_seen and dynamic_seen:
        return evidence, ResolutionStatus.UNSUPPORTED_LAYOUT, True

    if dynamic_seen:
        plugin_root, issue = _dynamic_local_plugin_root(repo, project)
        if issue is not None:
            return evidence, issue, True
        assert plugin_root is not None
        catalog_evidence, issue = _parse_plugin_catalog(
            repo, plugin_root, entry_step="android/settings.gradle dynamic require.resolve includeBuild"
        )
        if catalog_evidence is not None:
            evidence.append(catalog_evidence)
        return evidence, issue, True

    normalized: list[Path] = []
    for unresolved, _rel, _raw in include_paths:
        try:
            target = unresolved.resolve(strict=False)
        except OSError:
            return evidence, ResolutionStatus.MALFORMED_EVIDENCE, True
        if target not in normalized:
            normalized.append(target)

    if len(normalized) != 1:
        return evidence, ResolutionStatus.UNSUPPORTED_LAYOUT, True

    plugin_root = normalized[0]
    if not plugin_root.exists() or not plugin_root.is_dir():
        return evidence, ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED, True

    catalog_evidence, issue = _parse_plugin_catalog(repo, plugin_root)
    if catalog_evidence is not None:
        evidence.append(catalog_evidence)
    return evidence, issue, True


def collect_agp(repo: Path, project: Path) -> ResolvedFact:
    candidates = (
        "settings.gradle", "settings.gradle.kts",
        "build.gradle", "build.gradle.kts",
        "app/build.gradle", "app/build.gradle.kts",
    )
    evidence: list[Evidence] = []
    unsupported_layout = False
    versionless_declaration = False
    malformed = False

    for relname in candidates:
        file = project / relname
        rel = _relative_source(repo, file)
        try:
            content = _safe_read(file)
        except OSError:
            if file.exists() or file.is_symlink():
                evidence.append(Evidence(None, EvidenceScope.DECLARED, rel, ("Gradle declaration source",)))
                malformed = True
            continue
        if content is None:
            continue
        text = _strip_comments(content)
        if ANDROID_ALIAS.search(text):
            unsupported_layout = True
        plugin_matches = list(PLUGIN_VERSION.finditer(text))
        android_id_matches = list(ANDROID_ID.finditer(text))
        if len(android_id_matches) > len(plugin_matches) or UNVERSIONED_CLASSPATH.search(text):
            versionless_declaration = True
        for match in plugin_matches:
            value = match.group(1)
            evidence.append(Evidence(value, EvidenceScope.DECLARED, rel, ("Android Gradle plugin declaration",)))
            if not VERSION.fullmatch(value):
                malformed = True
        for match in CLASSPATH_VERSION.finditer(text):
            value = match.group(1)
            evidence.append(Evidence(value, EvidenceScope.DECLARED, rel, ("com.android.tools.build:gradle classpath",)))
            if not VERSION.fullmatch(value):
                malformed = True

    rn_evidence, rn_issue, rn_seen = _discover_rn_local_dependency(repo, project)
    evidence.extend(rn_evidence)

    if rn_issue is ResolutionStatus.UNRESOLVED_DEPENDENCY_NOT_INSTALLED:
        return _resolved_fact("agp", evidence, hazard=rn_issue)
    if rn_issue is ResolutionStatus.MALFORMED_EVIDENCE:
        return _resolved_fact("agp", evidence, hazard=rn_issue)
    if rn_issue is ResolutionStatus.UNSUPPORTED_LAYOUT:
        return _resolved_fact("agp", evidence, hazard=rn_issue)
    if malformed:
        return _resolved_fact("agp", evidence, hazard=ResolutionStatus.MALFORMED_EVIDENCE)

    numeric_values = {item.value for item in evidence if item.value is not None}
    if len(numeric_values) > 1:
        return _resolved_fact("agp", evidence)

    # A generic version-catalog/plugin-alias mechanism can affect AGP resolution,
    # but is deliberately outside this sprint. The RN includeBuild path above is
    # the only supported local-dependency mechanism.
    if unsupported_layout:
        return _resolved_fact("agp", evidence, hazard=ResolutionStatus.UNSUPPORTED_LAYOUT)

    # A versionless declaration is normal in modern RN when the supported local
    # RN Gradle Plugin evidence was successfully obtained. Otherwise it remains
    # a recognized-but-unsupported resolution mechanism.
    has_local_value = any(
        item.scope is EvidenceScope.LOCAL_DEPENDENCY and item.value is not None
        for item in evidence
    )
    if versionless_declaration and not has_local_value:
        return _resolved_fact("agp", evidence, hazard=ResolutionStatus.UNSUPPORTED_LAYOUT)

    if rn_seen and not has_local_value and not numeric_values:
        return _resolved_fact("agp", evidence, hazard=ResolutionStatus.MALFORMED_EVIDENCE)

    return _resolved_fact("agp", evidence)


def collect_facts(path: str | Path) -> tuple[Path, ResolvedFact, ResolvedFact]:
    repo = Path(path).expanduser().resolve()
    if not repo.is_dir():
        raise ProjectInputError(f"Not an accessible directory: {path}")
    project = project_android_root(repo)
    return repo, collect_agp(repo, project), collect_gradle(repo, project)
