"""Adversarial complexity regression for dynamic RN includeBuild detection.

This module deliberately uses malformed Gradle text and does not run Node/Gradle.
"""
from time import perf_counter

import pytest

from rn_readiness.collector import _dynamic_rn_include_detected, _paren_closures


@pytest.mark.parametrize("kind", ["unclosed", "balanced", "unclosed_file"])
def test_large_malformed_or_nested_inputs_have_bounded_parse_time(kind):
    # These are under the collector's 1 MB source limit. The old closing-paren
    # scan repeats a suffix traversal for every unmatched includeBuild/new File.
    if kind == "unclosed":
        source = "includeBuild(" * 12000
    elif kind == "balanced":
        source = "includeBuild(" * 12000 + ")" * 12000
    else:
        source = "def plugin = new File(" * 9000

    start = perf_counter()
    assert _dynamic_rn_include_detected(source) is False
    # Generous CI bound, not a throughput benchmark; catches quadratic growth.
    assert perf_counter() - start < 3.0


def test_parentheses_index_handles_nested_and_unclosed_text():
    code = "prefix(()) tail ("
    closures = _paren_closures(code)
    opens = [i for i, char in enumerate(code) if char == "("]
    assert closures[opens[0]] == code.index(")", code.index(")") + 1)
    assert closures[opens[1]] == code.index(")")
    assert opens[-1] not in closures


@pytest.mark.parametrize("style", ["inline", "provider"])
def test_original_dynamic_react_native_wiring_still_recognized(style):
    resolver = "require.resolve('@react-native/gradle-plugin/package.json', { paths: [require.resolve('react-native/package.json')] })"
    if style == "inline":
        source = 'includeBuild(new File(["node", "--print", "' + resolver + '"].execute(null, rootDir).text.trim()).getParentFile())'
    else:
        source = (
            'def plugin = new File(providers.exec { commandLine("node", "--print", "'
            + resolver + '") }.standardOutput.asText.get().trim()).getParentFile()\n'
            'includeBuild(plugin)'
        )
    assert _dynamic_rn_include_detected(source) is True


def test_unrelated_require_resolve_string_does_not_count():
    source = (
        'includeBuild(new File("../unrelated"))\n'
        'def x = "require.resolve(\'@react-native/gradle-plugin/package.json\', '
        '{ paths: [require.resolve(\'react-native/package.json\')] })"'
    )
    assert _dynamic_rn_include_detected(source) is False
