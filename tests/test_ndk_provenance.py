"""NDK provenance trace: ownership, resolution kind, and false-positive guards."""
import json
from pathlib import Path

import pytest

from rn_readiness.cli import main
from rn_readiness.ndk_collector import _parse_ndk_lines, trace_ndk
from rn_readiness.ndk_models import NdkOwnerType, NdkResolutionKind
from rn_readiness.ndk_report import to_json
from rn_readiness.cli import run as scan_run


def _android_repo(tmp_path: Path, name: str = "app") -> Path:
    repo = tmp_path / name
    (repo / "android").mkdir(parents=True)
    return repo


def _write_project_gradle(repo: Path, content: str, *, kotlin: bool = False) -> None:
    filename = "build.gradle.kts" if kotlin else "build.gradle"
    (repo / "android" / filename).write_text(content, encoding="utf-8")


def _write_dependency(
    repo: Path,
    package_name: str,
    gradle_content: str,
    *,
    kotlin: bool = False,
    gradle_relpath: str = "android/build.gradle",
) -> None:
    if package_name.startswith("@"):
        org, pkg = package_name.split("/", 1)
        root = repo / "node_modules" / org / pkg
    else:
        root = repo / "node_modules" / package_name
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"name": package_name}), encoding="utf-8")
    if gradle_relpath.endswith(".kts"):
        gradle_path = root / gradle_relpath
    elif kotlin:
        gradle_path = root / gradle_relpath.replace("build.gradle", "build.gradle.kts")
    else:
        gradle_path = root / gradle_relpath
    gradle_path.parent.mkdir(parents=True, exist_ok=True)
    gradle_path.write_text(gradle_content, encoding="utf-8")


def test_project_literal_ndk_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'android { ndkVersion "27.1.12297006" }\n')
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.owner == "project"
    assert item.owner_type is NdkOwnerType.PROJECT
    assert item.value == "27.1.12297006"
    assert item.resolution_kind is NdkResolutionKind.LITERAL
    assert item.source == "android/build.gradle"


def test_kotlin_dsl_literal_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'android { ndkVersion = "26.1.10909125" }\n',
        kotlin=True,
    )
    result = trace_ndk(str(repo))
    assert result.declarations[0].resolution_kind is NdkResolutionKind.LITERAL
    assert result.declarations[0].value == "26.1.10909125"


def test_installed_dependency_literal_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_dependency(repo, "@acme/native-lib", 'android { ndkVersion "25.2.9519653" }\n')
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.owner == "@acme/native-lib"
    assert item.owner_type is NdkOwnerType.INSTALLED_DEPENDENCY
    assert item.value == "25.2.9519653"
    assert item.source == "node_modules/@acme/native-lib/android/build.gradle"


def test_project_and_dependency_different_literal_versions(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    _write_dependency(repo, "react-native-foo", 'ndkVersion "26.1.10909125"\n')
    result = trace_ndk(str(repo))
    literals = {d.value for d in result.declarations if d.resolution_kind is NdkResolutionKind.LITERAL}
    assert literals == {"27.1.12297006", "26.1.10909125"}
    assert result.attention_signals == ("dependency_literal_pin_differs_from_project",)


def test_project_and_dependency_same_literal_version(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    _write_dependency(repo, "react-native-foo", 'ndkVersion "27.1.12297006"\n')
    result = trace_ndk(str(repo))
    assert result.attention_signals == ()


def test_root_project_ext_ndk_version(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, "android { ndkVersion rootProject.ext.ndkVersion }\n")
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.resolution_kind is NdkResolutionKind.ROOT_INHERITED
    assert item.value is None


def test_helper_default_expression(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'android { ndkVersion getExtOrDefault("ndkVersion") }\n')
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    item = result.declarations[0]
    assert item.resolution_kind is NdkResolutionKind.UNSUPPORTED_EXPRESSION
    assert item.value is None
    assert "getExtOrDefault" in item.resolution_path[-1]


def test_has_property_ndk_version_is_not_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'if (rootProject.hasProperty("ndkVersion")) { println "skip" }\n'
        'def v = findProperty("ndkVersion")\n',
    )
    result = trace_ndk(str(repo))
    assert result.declarations == ()


def test_comments_and_string_literals_are_not_declarations(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        '// ndkVersion "99.0.0"\n'
        'def msg = "ndkVersion 99.0.0"\n'
        'println(msg)\n',
    )
    result = trace_ndk(str(repo))
    assert result.declarations == ()


def test_no_ndk_evidence(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'plugins { id "com.android.application" }\n')
    result = trace_ndk(str(repo))
    assert result.declarations == ()
    assert result.attention_signals == ()


def test_trace_ndk_json_is_deterministic_without_timestamp_or_machine_path(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    _write_dependency(repo, "dep-a", 'ndkVersion "26.0.0"\n')
    a = to_json(trace_ndk(str(repo)))
    b = to_json(trace_ndk(str(repo)))
    assert a == b
    assert str(tmp_path) not in a
    doc = json.loads(a)
    assert doc["scope"] == "NDK_PROVENANCE_TRACE"
    assert "timestamp" not in doc


def test_trace_ndk_does_not_modify_repository(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    before = [(x.relative_to(repo).as_posix(), x.read_bytes()) for x in sorted(repo.rglob("*")) if x.is_file()]
    trace_ndk(str(repo))
    after = [(x.relative_to(repo).as_posix(), x.read_bytes()) for x in sorted(repo.rglob("*")) if x.is_file()]
    assert before == after


def test_existing_r02_scan_unchanged_after_ndk_work(tmp_path):
    repo = _android_repo(tmp_path)
    wrapper = repo / "android/gradle/wrapper"
    wrapper.mkdir(parents=True)
    (repo / "android/build.gradle").write_text(
        'plugins { id "com.android.application" version "9.2.0" apply false }\n',
        encoding="utf-8",
    )
    (wrapper / "gradle-wrapper.properties").write_text(
        'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\n',
        encoding="utf-8",
    )
    analysis = scan_run(str(repo))
    assert analysis.status.value == "checks_passed"


def test_dependency_recursive_gradle_discovery(tmp_path):
    repo = _android_repo(tmp_path)
    _write_dependency(
        repo,
        "react-native",
        'android { ndkVersion = rootProject.properties["ndkVersion"].toString() }\n',
        kotlin=True,
        gradle_relpath="ReactAndroid/build.gradle.kts",
    )
    _write_dependency(
        repo,
        "react-native",
        "ndkVersion = libs.versions.ndkVersion.get()\n",
        kotlin=True,
        gradle_relpath="ReactAndroid/hermes-engine/build.gradle.kts",
    )
    result = trace_ndk(str(repo))
    by_source = {(d.source, d.resolution_kind) for d in result.declarations}
    assert (
        "node_modules/react-native/ReactAndroid/build.gradle.kts",
        NdkResolutionKind.ROOT_INHERITED,
    ) in {(s, k) for s, k in by_source}
    assert (
        "node_modules/react-native/ReactAndroid/hermes-engine/build.gradle.kts",
        NdkResolutionKind.UNSUPPORTED_EXPRESSION,
    ) in {(s, k) for s, k in by_source}


def test_dependency_root_properties_ndk_inherited(tmp_path):
    repo = _android_repo(tmp_path)
    _write_dependency(
        repo,
        "react-native-safe-area-context",
        "ndkVersion rootProject.ext.ndkVersion\n",
        gradle_relpath="android/build.gradle",
    )
    item = trace_ndk(str(repo)).declarations[0]
    assert item.owner == "react-native-safe-area-context"
    assert item.resolution_kind is NdkResolutionKind.ROOT_INHERITED


def test_dependency_prunes_nested_node_modules_and_build(tmp_path):
    repo = _android_repo(tmp_path)
    root = repo / "node_modules" / "acme-lib"
    root.mkdir(parents=True)
    (root / "package.json").write_text('{"name":"acme-lib"}', encoding="utf-8")
    (root / "lib" / "build.gradle").parent.mkdir(parents=True)
    (root / "lib" / "build.gradle").write_text('ndkVersion "1.2.3"\n', encoding="utf-8")
    nested = root / "lib" / "node_modules" / "evil" / "android"
    nested.mkdir(parents=True)
    (nested / "build.gradle").write_text('ndkVersion "9.9.9"\n', encoding="utf-8")
    build_dir = root / "lib" / "build" / "generated"
    build_dir.mkdir(parents=True)
    (build_dir / "build.gradle").write_text('ndkVersion "8.8.8"\n', encoding="utf-8")
    result = trace_ndk(str(repo))
    values = {d.value for d in result.declarations if d.owner == "acme-lib"}
    assert values == {"1.2.3"}


def test_deep_only_gradle_path_is_discovered(tmp_path):
    repo = _android_repo(tmp_path)
    pkg = repo / "node_modules" / "deep-native-package"
    gradle = pkg / "native" / "android" / "module" / "build.gradle"
    gradle.parent.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name":"deep-native-package"}', encoding="utf-8")
    gradle.write_text('ndkVersion "26.0.1"\n', encoding="utf-8")
    item = next(d for d in trace_ndk(str(repo)).declarations if d.owner == "deep-native-package")
    assert item.value == "26.0.1"
    assert item.source == "node_modules/deep-native-package/native/android/module/build.gradle"


def test_glob_star_slash_star_does_not_erase_ndk_lines(tmp_path):
    repo = _android_repo(tmp_path)
    _write_dependency(
        repo,
        "hermes-like",
        'fileTree("build").include("**/*.cmake", "**/*.marks")\n'
        'ndkVersion = rootProject.properties["ndkVersion"].toString()\n',
        kotlin=True,
        gradle_relpath="ReactAndroid/hermes-engine/build.gradle.kts",
    )
    result = trace_ndk(str(repo))
    assert any(
        d.resolution_kind is NdkResolutionKind.ROOT_INHERITED
        for d in result.declarations
        if d.owner == "hermes-like"
    )


def test_same_file_preserves_root_inherited_and_unsupported(tmp_path):
    repo = _android_repo(tmp_path)
    _write_dependency(
        repo,
        "dual-shape",
        'ndkVersion = rootProject.properties["ndkVersion"].toString()\n'
        "ndkVersion = libs.versions.ndkVersion.get()\n",
        kotlin=True,
        gradle_relpath="android/build.gradle.kts",
    )
    kinds = [d.resolution_kind for d in trace_ndk(str(repo)).declarations]
    assert kinds.count(NdkResolutionKind.ROOT_INHERITED) == 1
    assert kinds.count(NdkResolutionKind.UNSUPPORTED_EXPRESSION) == 1


def test_cli_trace_ndk_json(tmp_path, capsys):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    assert main(["trace-ndk", str(repo), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["declarations"][0]["value"] == "27.1.12297006"


def test_block_comment_does_not_emit_literal(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        "/* ndkVersion \"99.0.0\" */\n"
        'ndkVersion "27.1.12297006"\n',
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.1.12297006"


def test_multiline_block_comment_does_not_emit_literal(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        "/**\n * ndkVersion \"99.0.0\"\n */\n"
        'ndkVersion "27.1.12297006"\n',
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.1.12297006"


def test_triple_quoted_string_does_not_emit_literal(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'val doc = """\nndkVersion "99.0.0"\n"""\n'
        'ndkVersion "27.1.12297006"\n',
        kotlin=True,
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.1.12297006"


def test_url_with_slashes_does_not_truncate_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'def url = "https://example.com/path"\n'
        'ndkVersion "27.1.12297006"\n',
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.1.12297006"


def test_glob_and_declaration_on_same_file(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'fileTree("build").include("**/*.cmake", "**/*.marks")\n'
        'ndkVersion "27.1.12297006"\n',
    )
    result = trace_ndk(str(repo))
    assert any(d.value == "27.1.12297006" for d in result.declarations)


def test_property_key_ndk_version_is_not_lhs_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'if (rootProject.properties["ndkVersion"] != null) {\n'
        '    ndkVersion = rootProject.properties["ndkVersion"].toString()\n'
        "}\n",
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].resolution_kind is NdkResolutionKind.ROOT_INHERITED


def test_non_declaration_reads_do_not_emit(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        "println(rootProject.ext.ndkVersion)\n"
        "logger.info(ndkVersion)\n"
        'if (x.ndkVersion == "27") { }\n'
        'val ndkVersion = "27.0.0"\n'
        "def ndkVersion = safeExtGet(\"ndkVersion\")\n"
        'var ndkVersion = "27.0.0"\n'
        'ext { cfg = [ndkVersion: "27.0.0"] }\n',
        kotlin=True,
    )
    assert trace_ndk(str(repo)).declarations == ()


def test_compound_expressions_are_unsupported_not_literal_or_root(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'ndkVersion "27.0.0" + suffix\n'
        'ndkVersion = "27.0.0" ?: other\n'
        "ndkVersion rootProject.ext.ndkVersion ?: \"26.1.1\"\n"
        'ndkVersion rootProject.ext.ndkVersion.toString().replace("a","b")\n',
    )
    kinds = [d.resolution_kind for d in trace_ndk(str(repo)).declarations]
    assert kinds == [NdkResolutionKind.UNSUPPORTED_EXPRESSION] * 4


def test_has_property_same_line_literal_still_found(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'if (rootProject.hasProperty("ndkVersion")) ndkVersion "27.0.0"\n',
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.0.0"


def test_has_property_same_line_root_properties_still_found(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'if (rootProject.hasProperty("ndkVersion")) {\n'
        '    ndkVersion = rootProject.properties["ndkVersion"].toString()\n'
        "}\n",
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].resolution_kind is NdkResolutionKind.ROOT_INHERITED


def test_trace_ndk_android_subdir_does_not_scan_parent_node_modules(tmp_path):
    app = tmp_path / "app"
    android = app / "android"
    android.mkdir(parents=True)
    (android / "build.gradle").write_text('ndkVersion "27.1.12297006"\n', encoding="utf-8")
    parent_pkg = app / "node_modules" / "outside-pkg"
    parent_pkg.mkdir(parents=True)
    (parent_pkg / "package.json").write_text('{"name":"outside-pkg"}', encoding="utf-8")
    (parent_pkg / "android").mkdir()
    (parent_pkg / "android" / "build.gradle").write_text('ndkVersion "99.0.0"\n', encoding="utf-8")
    result = trace_ndk(str(android))
    owners = {d.owner for d in result.declarations}
    assert owners == {"project"}
    assert str(tmp_path) not in to_json(result)


def test_malformed_package_json_does_not_crash_or_invent_owner(tmp_path):
    repo = _android_repo(tmp_path)
    root = repo / "node_modules" / "bad-json"
    root.mkdir(parents=True)
    (root / "package.json").write_text("[]", encoding="utf-8")
    (root / "android").mkdir()
    (root / "android" / "build.gradle").write_text('ndkVersion "1.2.3"\n', encoding="utf-8")
    assert trace_ndk(str(repo)).declarations == ()


def test_package_json_bom_and_non_dict_safe(tmp_path):
    repo = _android_repo(tmp_path)
    root = repo / "node_modules" / "bom-pkg"
    root.mkdir(parents=True)
    (root / "package.json").write_bytes(b"\xef\xbb\xbf" + b'"just-a-string"')
    (root / "android").mkdir()
    (root / "android" / "build.gradle").write_text('ndkVersion "1.2.3"\n', encoding="utf-8")
    assert trace_ndk(str(repo)).declarations == ()


def test_has_property_pad_preserves_coordinate_space_no_comment_fabrication(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'x.hasProperty("ndkVersion"); a = 1; b = 2; c = 3 // ndkVersion "99.0.0"\n',
    )
    assert trace_ndk(str(repo)).declarations == ()


def test_has_property_pad_allows_real_decl_after_comment_segment(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'x.hasProperty("ndkVersion") ; ndkVersion "27.0.0" ; /* ndkVersion "99.0.0" */\n',
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.0.0"


def test_local_ndk_bindings_never_emit(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'android { val ndkVersion = "27.0.0" }\n'
        'afterEvaluate { String ndkVersion = "1.2.3" }\n'
        'String ndkVersion = "27.0.0"\n'
        'final def ndkVersion = "27.0.0"\n'
        'const val ndkVersion = "27.0.0"\n'
        'private val ndkVersion = "27.0.0"\n',
        kotlin=True,
    )
    assert trace_ndk(str(repo)).declarations == ()


def test_reads_comparisons_and_map_keys_never_emit(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'if (a && ndkVersion == "27") { }\n'
        'x = ndkVersion ?: "26"\n'
        "compileSdk = ndkVersion.toInteger()\n"
        "foo(a, ndkVersion)\n"
        "y = c ? ndkVersion : o\n"
        'ndkVersion == "27.1.1"\n'
        'ndkVersion != "27.1.1"\n'
        'ndkVersion += "27.1.1"\n'
        'ndkVersion: "27.0.0"\n'
        'foo(\n    ndkVersion: "27.0.0"\n)\n',
    )
    assert trace_ndk(str(repo)).declarations == ()


def test_trailing_comments_keep_literal_and_root_inherited(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'ndkVersion "27.1.1" // pinned\n'
        'ndkVersion "28.0.0" /* pinned */\n'
        "ndkVersion rootProject.ext.ndkVersion // inherited\n",
    )
    result = trace_ndk(str(repo))
    kinds = {d.resolution_kind for d in result.declarations}
    assert NdkResolutionKind.LITERAL in kinds
    assert NdkResolutionKind.ROOT_INHERITED in kinds
    for item in result.declarations:
        assert "//" not in item.resolution_path[-1]
        assert "/*" not in item.resolution_path[-1]


def test_unmatched_quote_line_does_not_hide_next_line(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'def r = /"/\n'
        'ndkVersion "27.1.1"\n',
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.1.1"


def test_ext_block_ndk_literal_single_and_multiline_same(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ext { ndkVersion = "28.0.0" }\n')
    single = trace_ndk(str(repo)).declarations
    _write_project_gradle(
        repo,
        "ext {\n    ndkVersion = \"28.0.0\"\n}\n",
    )
    multi = trace_ndk(str(repo)).declarations
    assert len(single) == len(multi) == 1
    assert single[0].resolution_kind == multi[0].resolution_kind == NdkResolutionKind.LITERAL
    assert single[0].value == multi[0].value == "28.0.0"


def test_ext_map_entry_still_no_declaration(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ext { cfg = [ndkVersion: "27.0.0"] }\n')
    assert trace_ndk(str(repo)).declarations == ()


def test_attention_signal_skips_example_app_paths(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'ndkVersion "27.1.12297006"\n')
    ex = repo / "node_modules" / "lib" / "example" / "android" / "app"
    ex.mkdir(parents=True)
    (repo / "node_modules" / "lib" / "package.json").write_text('{"name":"lib"}', encoding="utf-8")
    (ex / "build.gradle").write_text('ndkVersion "21.0.0"\n', encoding="utf-8")
    result = trace_ndk(str(repo))
    assert any(d.source.endswith("example/android/app/build.gradle") for d in result.declarations)
    assert result.attention_signals == ()


def test_round3_h1_reads_and_named_args_emit_nothing(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        "foo(a, ndkVersion, b)\n"
        "foo(\n  compileSdk,\n  ndkVersion,\n  target\n)\n"
        'x = "v=" + ndkVersion + "!"\n'
        'if (x == ndkVersion && y) { }\n'
        "x = [a, ndkVersion]\n"
        "def ok = a || ndkVersion || b\n"
        'return ndkVersion + "x"\n'
        'Log.d("t", ndkVersion + 1)\n'
        "mapOf(\n  ndkVersion to \"27\"\n)\n"
        'configure(compileSdk = 34, ndkVersion = "27.0.0")\n',
    )
    assert trace_ndk(str(repo)).declarations == ()


def test_round3_h1_get_ext_or_default_still_unsupported(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'android { ndkVersion getExtOrDefault("ndkVersion") }\n')
    item = trace_ndk(str(repo)).declarations[0]
    assert item.resolution_kind is NdkResolutionKind.UNSUPPORTED_EXPRESSION


def test_round3_m1_nested_kts_comment_no_fabrication(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        "/* a /* b */\nndkVersion \"99.0.0\"\n*/\nndkVersion \"27.1.1\"\n",
        kotlin=True,
    )
    result = trace_ndk(str(repo))
    assert len(result.declarations) == 1
    assert result.declarations[0].value == "27.1.1"


def test_round3_m1_groovy_non_nested_comment_behavior(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        "/* a /* b */\nndkVersion \"99.0.0\"\n*/\nndkVersion \"27.1.1\"\n",
        kotlin=False,
    )
    result = trace_ndk(str(repo))
    assert any(d.value == "27.1.1" for d in result.declarations)


def test_round3_m2_cross_line_continuations_are_unsupported(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        "ndkVersion = rootProject.ext.ndkVersion\n    ?: \"26.1.1\"\n"
        "ndkVersion = rootProject.ext.ndkVersion\n    .replace(\"a\",\"b\")\n"
        'ndkVersion = "27.1.1"\n    .replace("2","3")\n'
        'ndkVersion = rootProject.properties["ndkVersion"].toString()\n    .trim()\n',
    )
    content = (repo / "android" / "build.gradle").read_text(encoding="utf-8")
    declarations = _parse_ndk_lines(
        content,
        owner="project",
        owner_type=NdkOwnerType.PROJECT,
        source="android/build.gradle",
    )
    kinds = [d.resolution_kind for d in declarations]
    assert kinds == [NdkResolutionKind.UNSUPPORTED_EXPRESSION] * 4
    assert all(d.resolution_path[-1] == "continued_expression" for d in declarations)


def test_round3_m3_typed_locals_emit_nothing(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(
        repo,
        'List<String> ndkVersion = "27.0.0"\n'
        'java.lang.String ndkVersion = "27.0.0"\n'
        'int ndkVersion = "27.0.0"\n'
        'String[] ndkVersion = "27.0.0"\n',
        kotlin=True,
    )
    assert trace_ndk(str(repo)).declarations == ()


def test_round3_conditional_command_literal_preserved(tmp_path):
    repo = _android_repo(tmp_path)
    _write_project_gradle(repo, 'if (rootProject.hasProperty("ndkVersion")) ndkVersion "27.0.0"\n')
    assert trace_ndk(str(repo)).declarations[0].value == "27.0.0"


def test_junction_package_outside_node_modules_is_skipped(tmp_path):
    import subprocess
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows junction test")
    outside = tmp_path / "outside_pkg"
    (outside / "android").mkdir(parents=True)
    (outside / "package.json").write_text('{"name":"evil-outside"}', encoding="utf-8")
    (outside / "android" / "build.gradle").write_text('ndkVersion "99.0.0"\n', encoding="utf-8")
    repo = _android_repo(tmp_path)
    (repo / "node_modules").mkdir(exist_ok=True)
    link = repo / "node_modules" / "evil"
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"junction creation unavailable: {proc.stderr.strip()}")
    result = trace_ndk(str(repo))
    assert not any(d.owner == "evil-outside" for d in result.declarations)
    assert not any(d.value == "99.0.0" for d in result.declarations)


def test_package_traversal_containment_skips_escape(tmp_path):
    if not hasattr(Path, "symlink_to"):
        pytest.skip("symlinks unavailable")
    repo = _android_repo(tmp_path)
    pkg = repo / "node_modules" / "escape-pkg"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name":"escape-pkg"}', encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "build.gradle").write_text('ndkVersion "99.0.0"\n', encoding="utf-8")
    try:
        (pkg / "link-out").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    (pkg / "lib" / "build.gradle").parent.mkdir(parents=True)
    (pkg / "lib" / "build.gradle").write_text('ndkVersion "26.0.0"\n', encoding="utf-8")
    result = trace_ndk(str(repo))
    values = {d.value for d in result.declarations if d.owner == "escape-pkg"}
    assert values == {"26.0.0"}
    blob = to_json(result)
    assert str(tmp_path) not in blob
    assert "outside" not in blob or "99.0.0" not in blob
