#!/usr/bin/env python3
"""Read-only ELF PT_LOAD / APK ZIP offset evidence. Not Android release certification.

Checks .so / .aar / .apk. No Gradle/SDK, no ZIP extraction, no network.
Never infers which Maven coordinate introduced a library into an app.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

PAGE = 16384
MAX_ARCHIVE_BYTES = 768 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_SO_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20000
MAX_SO_ENTRIES = 512
MAX_HEADERS = 4096
MAX_HEADER_READ = 512 * 1024


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def elf_load_segments(prefix: bytes) -> dict:
    """Read bounded ELF32/ELF64 program headers, not a full ELF validator."""
    if len(prefix) < 64 or prefix[:4] != b'\x7fELF':
        return {'status': 'UNKNOWN_NOT_ELF_OR_TRUNCATED'}
    klass, endian_tag = prefix[4], prefix[5]
    if klass not in (1, 2) or endian_tag not in (1, 2) or prefix[6] != 1:
        return {'status': 'UNKNOWN_UNSUPPORTED_ELF_HEADER'}
    byteorder = '<' if endian_tag == 1 else '>'
    if klass == 1:
        hdr_fmt, ph_fmt, min_len = byteorder + 'I', byteorder + 'IIIIIIII', 32
        phoff = struct.unpack_from(hdr_fmt, prefix, 28)[0]
        phentsize, phnum = struct.unpack_from(byteorder + 'HH', prefix, 42)
        abi = 'ELF32'
    else:
        ph_fmt, min_len = byteorder + 'IIQQQQQQ', 56
        phoff = struct.unpack_from(byteorder + 'Q', prefix, 32)[0]
        phentsize, phnum = struct.unpack_from(byteorder + 'HH', prefix, 54)
        abi = 'ELF64'
    if phnum in (0, 0xffff) or phnum > MAX_HEADERS or phentsize < min_len or phentsize > 1024:
        return {'status': 'UNKNOWN_PROGRAM_HEADER_LAYOUT', 'elf_class': abi}
    if phoff + phentsize * phnum > len(prefix):
        return {'status': 'UNKNOWN_PROGRAM_HEADERS_NOT_IN_BOUNDED_PREFIX', 'elf_class': abi}
    segments = []
    for i in range(phnum):
        header = struct.unpack_from(ph_fmt, prefix, phoff + i * phentsize)
        if klass == 1:
            ptype, offset, vaddr, _paddr, _filesz, _memsz, _flags, align = header
        else:
            ptype, _flags, offset, vaddr, _paddr, _filesz, _memsz, align = header
        if ptype != 1:  # PT_LOAD
            continue
        is_power_two = align > 0 and (align & (align - 1)) == 0
        compatible_16k = bool(is_power_two and align >= PAGE and (offset - vaddr) % PAGE == 0)
        segments.append({'index': i, 'p_align': align, 'offset': offset, 'vaddr': vaddr,
                         'aligned_16k': compatible_16k})
    if not segments:
        return {'status': 'UNKNOWN_NO_PT_LOAD', 'elf_class': abi, 'segments': []}
    return {'status': 'ELF_PT_LOAD_16K_ALIGNED' if all(x['aligned_16k'] for x in segments)
            else 'ATTENTION_ELF_PT_LOAD_UNALIGNED', 'elf_class': abi, 'segments': segments}


def archive_payload_offset(archive, zinfo: zipfile.ZipInfo) -> int | None:
    """Read local ZIP header; offsets are about final APK, not AAR/APK provenance."""
    fp = archive.fp
    if fp is None:
        return None
    here = fp.tell()
    try:
        fp.seek(zinfo.header_offset)
        header = fp.read(30)
        if len(header) != 30 or header[:4] != b'PK\x03\x04':
            return None
        name_size, extra_size = struct.unpack_from('<HH', header, 26)
        return zinfo.header_offset + 30 + name_size + extra_size
    finally:
        fp.seek(here)


def read_member(archive: zipfile.ZipFile, zinfo: zipfile.ZipInfo) -> dict:
    if zinfo.flag_bits & 0x1:
        return {'status': 'UNKNOWN_ENCRYPTED_MEMBER'}
    if zinfo.file_size > MAX_MEMBER_BYTES:
        return {'status': 'UNKNOWN_MEMBER_TOO_LARGE', 'size': zinfo.file_size}
    h = hashlib.sha256()
    head = bytearray()
    count = 0
    try:
        with archive.open(zinfo, 'r') as member:
            while True:
                buf = member.read(256 * 1024)
                if not buf:
                    break
                count += len(buf)
                if count > MAX_MEMBER_BYTES:
                    return {'status': 'UNKNOWN_MEMBER_TOO_LARGE', 'size': count}
                h.update(buf)
                if len(head) < MAX_HEADER_READ:
                    head.extend(buf[:MAX_HEADER_READ - len(head)])
    except (OSError, RuntimeError, EOFError, ValueError, zipfile.BadZipFile, NotImplementedError):
        return {'status': 'UNKNOWN_MEMBER_UNREADABLE'}
    if count != zinfo.file_size:
        return {'status': 'UNKNOWN_MEMBER_SIZE_MISMATCH'}
    return {'status': 'READ', 'sha256': h.hexdigest(), 'size': count, 'prefix': bytes(head)}


# This gate follows the official Android 16 KiB ELF check for 64-bit ABI
# (`arm64-v8a`, `x86_64`). Preserve 32-bit alignment as raw evidence, but
# never let it drive a 64-bit Google Play page-size attention finding.
ABI64 = frozenset({'arm64-v8a', 'x86_64'})
ABI32 = frozenset({'armeabi-v7a', 'x86'})
KNOWN_ABIS = ABI64 | ABI32


def archive_entry_identity(path: str, fmt: str) -> tuple[str | None, str]:
    """AAR JNI entries and Prefab build inputs are different roles.

    This is archive-path ownership, not project/Gradle dependency ownership.
    """
    pieces = path.replace('\\', '/').split('/')
    if fmt == 'aar':
        if len(pieces) == 3 and pieces[0] == 'jni' and pieces[1] in KNOWN_ABIS:
            return pieces[1], 'AAR_JNI_SOURCE'
        if (len(pieces) >= 6 and pieces[0] == 'prefab' and pieces[1] == 'modules'
                and pieces[3] == 'libs' and pieces[4].startswith('android.')
                and pieces[4][8:] in KNOWN_ABIS):
            return pieces[4][8:], 'AAR_PREFAB_BUILD_INPUT'
    if fmt == 'apk':
        if len(pieces) == 3 and pieces[0] == 'lib' and pieces[1] in KNOWN_ABIS:
            return pieces[1], 'APK_PACKAGED_NATIVE'
    return None, 'UNCLASSIFIED_NATIVE_ENTRY'


def alignment_summary(libraries: list[dict], fmt: str) -> dict:
    """Avoid 32-bit false alarms and never certify an app from an AAR."""
    roles = {}
    abi_count = {}
    tracked64 = []
    informational32 = 0
    unidentified = 0
    for item in libraries:
        role = item.get('source_role', 'RAW_SO_INPUT' if fmt == 'so' else 'UNCLASSIFIED_NATIVE_ENTRY')
        abi = item.get('abi_from_archive_path')
        roles[role] = roles.get(role, 0) + 1
        abi_count[abi or 'UNKNOWN'] = abi_count.get(abi or 'UNKNOWN', 0) + 1
        if abi in ABI64:
            tracked64.append(item)
        elif abi in ABI32:
            informational32 += 1
        else:
            unidentified += 1
    result = {
        'rule_scope': 'ANDROID_16K_64BIT_ELF_AND_APK_PACKAGING_EVIDENCE',
        'source_roles': dict(sorted(roles.items())),
        'abis': dict(sorted(abi_count.items())),
        'evaluated_64bit_elf_entries': len(tracked64),
        'informational_32bit_elf_entries': informational32,
        'unclassified_native_entries': unidentified,
        'apk_zip_certified_by_official_zipalign': False,
        'runtime_or_release_certified': False,
    }
    if not libraries:
        result['status'] = 'NO_SO_ENTRIES_FOUND_NOT_RELEASE_CERTIFICATION'
    elif fmt == 'so':
        # Standalone file has no proven Android ABI or enclosing APK.
        if any(x['elf']['status'].startswith('UNKNOWN_') for x in libraries):
            result['status'] = 'UNKNOWN_RAW_ELF_INCOMPLETE'
        elif any(x['elf']['status'].startswith('ATTENTION_') for x in libraries):
            result['status'] = 'ATTENTION_RAW_ELF_ALIGNMENT_ABI_UNVERIFIED'
        else:
            result['status'] = 'OBSERVED_RAW_ELF_ALIGNMENT_ABI_UNVERIFIED'
    elif unidentified:
        result['status'] = 'UNKNOWN_UNCLASSIFIED_NATIVE_ENTRIES'
    elif not tracked64:
        result['status'] = 'NOT_EVALUATED_NO_64BIT_ABI_LIBRARIES'
    elif any(x['elf'].get('elf_class') != 'ELF64' or
             x['elf']['status'].startswith('UNKNOWN_') or
             x.get('apk_zip_16k', '').startswith('UNKNOWN_') for x in tracked64):
        result['status'] = 'UNKNOWN_64BIT_NATIVE_EVIDENCE'
    elif any(x['elf']['status'].startswith('ATTENTION_') or
             x.get('apk_zip_16k', '').startswith('ATTENTION_') for x in tracked64):
        result['status'] = 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE'
    else:
        result['status'] = 'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION'
    return result


def classify(libraries: list[dict], fmt: str) -> str:
    return alignment_summary(libraries, fmt)['status']


def inspect(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError('ARTIFACT_MISSING_OR_SYMLINK')
    path = path.resolve()
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('ARTIFACT_TOO_LARGE_FOR_EXPERIMENT')
    fmt = path.suffix.lower().lstrip('.')
    if fmt not in ('apk', 'aar', 'so'):
        raise ValueError('SUPPORTED_FORMATS_SO_AAR_APK_ONLY')
    file_sha = hashlib.sha256()
    with path.open('rb') as f:
        while buf := f.read(1024 * 1024):
            file_sha.update(buf)
    libraries: list[dict] = []
    if fmt == 'so':
        with path.open('rb') as f:
            prefix = f.read(MAX_HEADER_READ)
        libraries = [{'entry': path.name, 'source_role': 'RAW_SO_INPUT', 'abi_from_archive_path': None,
                      'sha256': file_sha.hexdigest(), 'size': path.stat().st_size,
                      'elf': elf_load_segments(prefix), 'apk_zip_16k': 'NOT_APPLICABLE_RAW_SO'}]
    else:
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > MAX_ARCHIVE_ENTRIES:
                    raise ValueError('TOO_MANY_ARCHIVE_ENTRIES')
                sos = [m for m in members if m.filename.lower().endswith('.so') and not m.is_dir()]
                if len(sos) > MAX_SO_ENTRIES:
                    raise ValueError('TOO_MANY_SO_ENTRIES')
                if sum(m.file_size for m in sos) > MAX_TOTAL_SO_BYTES:
                    raise ValueError('TOTAL_NATIVE_PAYLOAD_BUDGET_EXCEEDED')
                seen = set()
                for member in sos:
                    if member.filename in seen:
                        libraries.append({'entry': member.filename, 'elf': {'status': 'UNKNOWN_DUPLICATE_ENTRY'},
                                          'apk_zip_16k': 'UNKNOWN_DUPLICATE_ENTRY', 'source_role': 'UNCLASSIFIED_NATIVE_ENTRY'})
                        continue
                    seen.add(member.filename)
                    data = read_member(archive, member)
                    if data['status'] == 'READ':
                        elf = elf_load_segments(data['prefix'])
                        length = data['size']
                        sha = data['sha256']
                    else:
                        elf = {'status': data['status']}
                        length = member.file_size
                        sha = None
                    zip_status = 'NOT_APPLICABLE_AAR_SOURCE_PACKAGING'
                    payload_offset = None
                    if fmt == 'apk':
                        if member.compress_type == zipfile.ZIP_STORED:
                            offset = archive_payload_offset(archive, member)
                            payload_offset = offset
                            zip_status = ('UNKNOWN_LOCAL_ZIP_HEADER' if offset is None else
                                          'APK_UNCOMPRESSED_SO_16K_ALIGNED' if offset % PAGE == 0 else
                                          'ATTENTION_UNCOMPRESSED_SO_NOT_16K_ALIGNED')
                        else:
                            zip_status = 'NOT_APPLICABLE_COMPRESSED_SO'
                    abi, source_role = archive_entry_identity(member.filename, fmt)
                    libraries.append({'entry': member.filename, 'abi_from_archive_path': abi,
                                      'source_role': source_role,
                                      'gate_disposition': ('EVALUATED_64BIT_ELF_EVIDENCE' if abi in ABI64 else
                                                           'INFORMATIONAL_32BIT_ABI_NOT_64BIT_GATE' if abi in ABI32 else
                                                           'UNKNOWN_ABI_UNCLASSIFIED'),
                                      'size': length, 'sha256': sha, 'compression': 'STORED' if member.compress_type == 0 else 'COMPRESSED',
                                      'elf': elf, 'apk_zip_16k': zip_status, 'apk_zip_payload_offset': payload_offset})
        except zipfile.BadZipFile as e:
            raise ValueError('INVALID_ZIP_ARCHIVE') from e
    return {
        'schema_version': 'rn-upgrade-native-evidence-0.2',
        'artifact_name': path.name, 'artifact_format': fmt, 'artifact_sha256': file_sha.hexdigest(),
        'size_bytes': path.stat().st_size,
        'artifact_path': str(path),
        'container_owner': 'INPUT_ARTIFACT_ONLY',
        'maven_dependency_coordinate': 'NOT_VERIFIED',
        'native_library_count': len(libraries),
        'status': classify(libraries, fmt),
        'alignment_summary': alignment_summary(libraries, fmt),
        'libraries': libraries,
        'limitations': [
            'Checks ELF PT_LOAD alignment and APK uncompressed .so ZIP payload alignment only.',
            'APK ZIP check is narrower than official zipalign -c -P 16 -v 4; it is not a substitute.',
            'An AAR is not the final APK: ZIP offset in AAR cannot establish APK packaging alignment.',
            'No dependency owner/Maven coordinate proven; requires Gradle resolution or provenance evidence.',
            'AAB, runtime on 16 KB device, extractNativeLibs, page-size code assumptions, Play release not tested.',
            '32-bit ABI p_align is reported as evidence, not a 64-bit 16 KB release warning.',
            'AAR JNI source vs Prefab build-input libraries are distinguished; Prefab is not proof of APK packaging.',
            'No input archive content is extracted or modified.',
        ],
        'official_reference': 'https://developer.android.com/guide/practices/page-sizes',
    }


def fixture_elf(align: int, *, klass: int = 2) -> bytes:
    hdr = bytearray(256)
    hdr[:6] = b'\x7fELF' + bytes((klass, 1))
    hdr[6] = 1
    if klass == 2:
        struct.pack_into('<Q', hdr, 32, 64)
        struct.pack_into('<HH', hdr, 54, 56, 1)
        struct.pack_into('<IIQQQQQQ', hdr, 64, 1, 5, 0, 0, 0, 256, 256, align)
    else:
        struct.pack_into('<I', hdr, 28, 52)
        struct.pack_into('<HH', hdr, 42, 32, 1)
        struct.pack_into('<IIIIIIII', hdr, 52, 1, 0, 0, 0, 256, 256, 5, align)
    return bytes(hdr)


def self_test() -> None:
    checks = 0
    assert elf_load_segments(fixture_elf(4096))['status'] == 'ATTENTION_ELF_PT_LOAD_UNALIGNED'; checks += 1
    assert elf_load_segments(fixture_elf(16384))['status'] == 'ELF_PT_LOAD_16K_ALIGNED'; checks += 1
    assert elf_load_segments(fixture_elf(16384, klass=1))['status'] == 'ELF_PT_LOAD_16K_ALIGNED'; checks += 1
    assert elf_load_segments(b'bad')['status'].startswith('UNKNOWN_'); checks += 1
    with tempfile.TemporaryDirectory(prefix='rn-native-artifact-') as tmp:
        root = Path(tmp)
        for kind, align, expected in (('aar', 4096, 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE'),
                                      ('aar', 16384, 'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION'),
                                      ('apk', 16384, 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE')):
            archive = root / f'demo-{kind}-{align}.{kind}'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(('lib/' if kind == 'apk' else 'jni/') + 'arm64-v8a/libdemo.so', fixture_elf(align), compress_type=zipfile.ZIP_STORED)
            r = inspect(archive)
            assert r['status'] == expected, (r['status'], expected)
            assert r['maven_dependency_coordinate'] == 'NOT_VERIFIED'
            assert r['libraries'][0]['sha256'] == digest_bytes(fixture_elf(align))
            checks += 1
        with zipfile.ZipFile(root / 'empty.aar', 'w') as z:
            z.writestr('AndroidManifest.xml', '<manifest/>')
        assert inspect(root / 'empty.aar')['native_library_count'] == 0; checks += 1
        # Stored .so with an intentionally 16 KB aligned payload in final APK ZIP.
        aligned_apk = root / 'aligned.apk'
        name = 'lib/arm64-v8a/libdemo.so'
        # Initial local header is 30 bytes plus filename; pad via a valid ZIP extra-field.
        pad = (-30 - len(name.encode('utf-8'))) % PAGE
        if pad < 4:
            pad += PAGE
        zi = zipfile.ZipInfo(name)
        zi.compress_type = zipfile.ZIP_STORED
        zi.extra = struct.pack('<HH', 0xCAFE, pad - 4) + b'\x00' * (pad - 4)
        with zipfile.ZipFile(aligned_apk, 'w') as z:
            z.writestr(zi, fixture_elf(16384))
        aligned_result = inspect(aligned_apk)
        assert aligned_result['libraries'][0]['apk_zip_16k'] == 'APK_UNCOMPRESSED_SO_16K_ALIGNED'
        assert aligned_result['status'] == 'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION'; checks += 1
        (root / 'plain.so').write_bytes(fixture_elf(16384))
        assert inspect(root / 'plain.so')['status'] == 'OBSERVED_RAW_ELF_ALIGNMENT_ABI_UNVERIFIED'; checks += 1
        (root / 'bad.so').write_bytes(b'notelf')
        assert inspect(root / 'bad.so')['status'] == 'UNKNOWN_RAW_ELF_INCOMPLETE'; checks += 1
        (root / 'bad.aar').write_bytes(b'notzip')
        try: inspect(root / 'bad.aar')
        except ValueError as e: assert str(e) == 'INVALID_ZIP_ARCHIVE'; checks += 1
        else: raise AssertionError('bad ZIP accepted')
    with tempfile.TemporaryDirectory(prefix='rn-native-abi-gate-') as tmp:
        root = Path(tmp)
        mixed = root / 'mixed.aar'
        with zipfile.ZipFile(mixed, 'w') as z:
            z.writestr('jni/arm64-v8a/libnative.so', fixture_elf(16384), compress_type=zipfile.ZIP_DEFLATED)
            z.writestr('jni/armeabi-v7a/libnative.so', fixture_elf(4096, klass=1))
            z.writestr('prefab/modules/demo/libs/android.x86_64/libnative.so', fixture_elf(16384))
            z.writestr('prefab/modules/demo/libs/android.x86/libnative.so', fixture_elf(4096, klass=1))
        r = inspect(mixed)
        assert r['status'] == 'OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION'
        assert r['alignment_summary']['evaluated_64bit_elf_entries'] == 2
        assert r['alignment_summary']['informational_32bit_elf_entries'] == 2
        assert r['alignment_summary']['source_roles']['AAR_PREFAB_BUILD_INPUT'] == 2
        assert r['libraries'][1]['gate_disposition'] == 'INFORMATIONAL_32BIT_ABI_NOT_64BIT_GATE'
        checks += 1
        broken = root / 'bad64.aar'
        with zipfile.ZipFile(broken, 'w') as z:
            z.writestr('jni/arm64-v8a/libnative.so', fixture_elf(4096))
        assert inspect(broken)['status'] == 'ATTENTION_64BIT_ALIGNMENT_EVIDENCE'; checks += 1
        only32 = root / 'only32.aar'
        with zipfile.ZipFile(only32, 'w') as z:
            z.writestr('jni/armeabi-v7a/libnative.so', fixture_elf(4096, klass=1))
        assert inspect(only32)['status'] == 'NOT_EVALUATED_NO_64BIT_ABI_LIBRARIES'; checks += 1
        unknown64 = root / 'invalid64.aar'
        with zipfile.ZipFile(unknown64, 'w') as z:
            z.writestr('jni/arm64-v8a/libnative.so', fixture_elf(4096, klass=1))
        assert inspect(unknown64)['status'] == 'UNKNOWN_64BIT_NATIVE_EVIDENCE'; checks += 1
    print(f'NATIVE_ARTIFACT_SELF_TEST: PASS {checks}/16 (synthetic ELF/ZIP, not Android application)')


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--self-test':
        self_test()
    elif len(sys.argv) == 2:
        try:
            print(json.dumps(inspect(Path(sys.argv[1])), indent=2, ensure_ascii=False, sort_keys=True))
        except (ValueError, OSError) as exc:
            print('INPUT_ERROR: ' + str(exc), file=sys.stderr)
            sys.exit(4)
    else:
        print('usage: py -B inspect_native_artifact.py PATH_TO_SO_AAR_APK | --self-test', file=sys.stderr)
        sys.exit(4)
