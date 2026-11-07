"""Offline R03/R04 regression tests; never run external build tools."""
import json
from pathlib import Path

import pytest

from rn_readiness.windows_native_doctor import diagnose, main, InputError


LONG_RELATIVE = (
    'rngesturehandler_codegen_autolinked_build/CMakeFiles/'
    'react_codegen_rngesturehandler_codegen.dir/C_/nv/node_modules/'
    'react-native-gesture-handler/shared/shadowNodes/react/renderer/components/'
    'rngesturehandler_codegen'
)
WORKING = r'C:\nv\android\app\.cxx\Debug\o4dg6vr3\arm64-v8a'


def fixture(tmp_path: Path, *, ndk=r'C:\Users\Example Person\AppData\Local\Android\Sdk\ndk\27.1.12297006',
            log=None, include_cache=True):
    project = tmp_path / 'pilot'
    (project / 'android').mkdir(parents=True)
    log_file = tmp_path / 'build.log'
    log_file.write_text(log if log is not None else 'BUILD FAILED\n', encoding='utf-8')
    caches = []
    if include_cache:
        cache = project / 'android' / 'app' / '.cxx' / 'Debug' / 'abc' / 'arm64-v8a' / 'CMakeCache.txt'
        cache.parent.mkdir(parents=True)
        cache.write_text('CMAKE_ANDROID_NDK:UNINITIALIZED=' + ndk + '\n', encoding='utf-8')
        caches.append(cache)
    return project, log_file, caches


def run_case(tmp_path, *, log=None, ndk=None, version=None, directory=None, include_cache=True):
    kwargs = {'log': log, 'include_cache': include_cache}
    if ndk is not None:
        kwargs['ndk'] = ndk
    project, log_path, caches = fixture(tmp_path, **kwargs)
    return diagnose(project, log_path, caches, ninja_version=version, ninja_dir=directory)


def sample_log():
    return (
        'ld.lld: error: undefined symbol: std::__ndk1::__shared_count\n'
        '  C++ build system [build] failed while executing:\n'
        '      "C:\\\\Users\\\\Example Person\\\\Sdk\\\\cmake\\\\3.22.1\\\\bin\\\\ninja.exe" ^\n'
        '        -C ^\n'
        '        "C:\\\\nv\\\\android\\\\app\\\\.cxx\\\\Debug\\\\o4dg6vr3\\\\arm64-v8a" ^\n'
        '        appmodules\n'
        '  ninja: error: mkdir(' + LONG_RELATIVE + '): No such file or directory\n'
    )


def test_two_rules_suspected_on_observed_error_signatures(tmp_path):
    report = run_case(tmp_path, log=sample_log(), version='1.10.2')
    ndk, ninja = report['findings']
    assert ndk['status'] == 'SUSPECTED'
    assert ninja['status'] == 'SUSPECTED'
    assert ninja['evidence']['longest_mkdir_path_length'] == 261
    assert ninja['evidence']['ninja_version_below_1_12'] is True
    assert 'Example Person' not in json.dumps(report)
    assert r'C:\nv' not in json.dumps(report)


def test_ndk_path_is_risk_not_root_cause_without_linker_error(tmp_path):
    report = run_case(tmp_path, log='BUILD SUCCESSFUL')
    assert report['findings'][0]['status'] == 'RISK_SIGNAL'
    assert report['findings'][1]['status'] == 'NO_MATCH'


def test_arbitrary_undefined_symbol_does_not_trigger_cpp_signature(tmp_path):
    report = run_case(tmp_path, log='ld.lld: error: undefined symbol: my_app_symbol')
    assert report['findings'][0]['status'] == 'RISK_SIGNAL'


def test_clean_path_with_linker_failure_not_attributed_to_ndk_spaces(tmp_path):
    report = run_case(tmp_path, ndk=r'C:\ndk\27.1.12297006',
                      log='ld.lld: error: undefined symbol: __cxa_throw')
    assert report['findings'][0]['status'] == 'NOT_EVALUATED'


def test_no_cache_never_infers_effective_ndk_from_local_properties(tmp_path):
    project, log, caches = fixture(tmp_path, include_cache=False,
                                    log='ld.lld: error: undefined symbol: __cxa_throw')
    (project / 'android' / 'local.properties').write_text('ndk.dir=C:/Users/Example Person/SDK/ndk\n')
    report = diagnose(project, log, caches)
    finding = report['findings'][0]
    assert finding['status'] == 'NOT_EVALUATED'
    assert finding['evidence']['declared_ndk_path_contains_whitespace'] is True


def test_conflicting_cache_sources_fail_closed(tmp_path):
    project, log, caches = fixture(tmp_path, log='ld.lld: error: undefined symbol: __cxa_throw')
    cache2 = project / 'android' / 'app' / 'more' / 'CMakeCache.txt'
    cache2.parent.mkdir(parents=True)
    cache2.write_text('CMAKE_ANDROID_NDK:UNINITIALIZED=C:/ndk/27.1.12297006\n')
    assert diagnose(project, log, caches + [cache2])['findings'][0]['status'] == 'NOT_EVALUATED'


def test_wrapped_ninja_directory_line_reassembled(tmp_path):
    log = (
        'ninja: error: mkdir(' + LONG_RELATIVE.replace('/C_/nv/', '/C\n_/nv/')
        + '): No such file or directory\n'
    )
    report = run_case(tmp_path, log=log, version='1.10.2', directory=WORKING)
    assert report['findings'][1]['status'] == 'SUSPECTED'
    assert report['findings'][1]['evidence']['longest_mkdir_path_length'] == 261


def test_missing_or_new_ninja_version_never_claims_old_ninja(tmp_path):
    for ver in (None, '1.12.1'):
        report = run_case(tmp_path / (ver or 'unknown'), log=sample_log(), version=ver)
        finding = report['findings'][1]
        assert finding['status'] == 'RISK_SIGNAL'
        assert finding['evidence']['longest_mkdir_path_length'] == 261


def test_short_mkdir_path_does_not_claim_long_path_cause(tmp_path):
    log = '        -C ^\n        "C:\\nv"\nninja: error: mkdir(a/b): No such file or directory'
    report = run_case(tmp_path, log=log, version='1.10.2')
    assert report['findings'][1]['status'] == 'NOT_EVALUATED'


def test_ambiguous_working_directory_not_evaluated(tmp_path):
    log = 'ninja: error: mkdir(' + LONG_RELATIVE + '): No such file or directory'
    report = run_case(tmp_path, log=log, version='1.10.2')
    assert report['findings'][1]['status'] == 'NOT_EVALUATED'


def test_overlarge_log_refused(tmp_path):
    project, log, caches = fixture(tmp_path)
    with log.open('wb') as stream:
        stream.write(b'x' * (8_000_000 + 1))
    with pytest.raises(InputError, match='exceeds'):
        diagnose(project, log, caches)


def test_cache_outside_project_refused(tmp_path):
    project, log, _ = fixture(tmp_path, include_cache=False)
    extra = tmp_path / 'outside.txt'
    extra.write_text('CMAKE_ANDROID_NDK:UNINITIALIZED=C:/ndk\n')
    with pytest.raises(InputError, match='within the project'):
        diagnose(project, log, [extra])


def test_symlinked_cache_refused(tmp_path):
    project, log, _ = fixture(tmp_path, include_cache=False)
    target = project / 'real-cache'
    target.write_text('CMAKE_ANDROID_NDK:UNINITIALIZED=C:/ndk\n')
    link = project / 'link-cache'
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip('File symlinks not available on this platform')
    with pytest.raises(InputError):
        diagnose(project, log, [link])


def test_duplicate_ndk_cache_line_refused(tmp_path):
    project, log, caches = fixture(tmp_path)
    with caches[0].open('a') as stream:
        stream.write('CMAKE_ANDROID_NDK:UNINITIALIZED=C:/other\n')
    with pytest.raises(InputError, match='exactly one'):
        diagnose(project, log, caches)


def test_invalid_version_is_input_error(tmp_path):
    project, log, caches = fixture(tmp_path)
    with pytest.raises(InputError, match='numeric'):
        diagnose(project, log, caches, ninja_version='1.10.2; echo bad')


def test_cli_json_deterministic_and_read_only(tmp_path, capsys):
    project, log, caches = fixture(tmp_path, log=sample_log())
    before = [p.read_bytes() for p in (log, caches[0])]
    args = ['--project', str(project), '--build-log', str(log), '--cmake-cache', str(caches[0]),
            '--ninja-version', '1.10.2', '--json']
    assert main(args) == 0
    out1 = capsys.readouterr().out
    assert main(args) == 0
    out2 = capsys.readouterr().out
    assert out1 == out2
    assert json.loads(out1)['read_only'] is True
    assert str(tmp_path) not in out1
    assert before == [p.read_bytes() for p in (log, caches[0])]


def test_cli_bad_file_returns_4(tmp_path, capsys):
    project, log, caches = fixture(tmp_path)
    assert main(['--project', str(project), '--build-log', str(log) + '-missing']) == 4
    assert 'INPUT ERROR' in capsys.readouterr().err


@pytest.mark.parametrize('encoding,bom', [
    ('utf-16-le', b'\xff\xfe'),
    ('utf-16-be', b'\xfe\xff'),
    ('utf-8', b'\xef\xbb\xbf'),
])
def test_powershell_utf16_and_utf8_bom_logs_preserve_real_ninja_signature(tmp_path, encoding, bom):
    project, log, _ = fixture(tmp_path, include_cache=False)
    log.write_bytes(bom + sample_log().encode(encoding))
    report = diagnose(project, log, [], ninja_version='1.10.2')
    assert report['findings'][0]['status'] == 'NOT_EVALUATED'
    ninja = report['findings'][1]
    assert ninja['status'] == 'SUSPECTED'
    assert ninja['evidence']['longest_mkdir_path_length'] == 261


def test_bomless_utf16_log_refused_instead_of_false_no_match(tmp_path):
    project, log, _ = fixture(tmp_path, include_cache=False)
    log.write_bytes(sample_log().encode('utf-16-le'))
    with pytest.raises(InputError, match='BOM-less UTF-16'):
        diagnose(project, log, [], ninja_version='1.10.2')


def test_malformed_utf16_log_refused_instead_of_false_no_match(tmp_path):
    project, log, _ = fixture(tmp_path, include_cache=False)
    log.write_bytes(b'\xff\xfe' + b'\xff')
    with pytest.raises(InputError, match='Invalid utf-16-le'):
        diagnose(project, log, [], ninja_version='1.10.2')
