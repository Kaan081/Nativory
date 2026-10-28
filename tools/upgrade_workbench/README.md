# Nativory — experimental upgrade workbench (RN Upgrade Workbench alpha 0.1.5)

Experimental sibling scripts for historical Expo #50293 replay, Reanimated #10544 property semantics, native ELF/APK inspection and isolated Gradle AAR provenance. **Not integrated into the installed Nativory / `rn-readiness` scanner CLI.**

Scope: The generated NDK/GString case reproduces a Gradle property **type conversion**, not a genuine Reanimated module build failure or NDK selection; its *before* task deliberately fails when the old `as? String` cast drops the GString, its *after* task uses the upstream `CharSequence` conversion and must succeed. Both use identical root Groovy properties and separate workspace directories. **A passing report does not certify native binaries, AAB, Android SDK, release readiness, or saved time.** The report's `AFTER_LOG_CONTAINS_ARTIFACT_MARKER_UNATTESTED` is a generic label: for this case it refers to a printed **property value**, not a compiler artifact.

Test generator without Gradle:

```powershell
py -B .\prepare_ndk_gstring_case.py --self-test
```

Stage case in a new, empty destination (nothing touches this repository checkout):

```powershell
py -B .\prepare_ndk_gstring_case.py `
  --gradlew "$HOME\Downloads\rn-expo-sdk58-probe\android\gradlew.bat" `
  --output-root "$HOME\Downloads\rn-ndk-gstring-workbench-01"
```

**Explicit** controlled pair Gradle execution (may use cache/create files in the generated fixtures):

```powershell
py -B .\workbench.py verify `
  --manifest "$HOME\Downloads\rn-ndk-gstring-workbench-01\case.json" `
  --workspace "$HOME\Downloads\rn-ndk-gstring-workbench-01\cases" `
  --output "$HOME\Downloads\rn-ndk-gstring-workbench-01\verification-run-01" `
  --timeout 600 --execute
```

Expected if cached Gradle dependencies permit offline evaluation: `SCOPED_COMMAND_EVIDENCE_PASS`. Before task exits nonzero with `EXPECTED_OLD_GSTRING_CAST_REJECTED`; after task exits zero with `PATCHED_GSTRING_VALUE=27.1.12297006`.

If Gradle fails due to cache, JDK, filesystem, or wrapper issues, the Workbench should return `UNKNOWN_*`/`BLOCKED_*`. Report failures and do **not** reinterpret them as successful native fixes. To inspect:

```powershell
$r = Get-Content "$HOME\Downloads\rn-ndk-gstring-workbench-01\verification-run-01\report.json" -Raw | ConvertFrom-Json
$r | Select-Object case_id,scope,status
$r.runs.before | Select-Object exit_code,execution_error,elapsed_seconds,source_drift
$r.runs.after | Select-Object exit_code,execution_error,elapsed_seconds,source_drift
```

**Caveat:** The command runner is not a sandbox: run only locally trusted fixtures; Gradle may execute code and write to cache. This package contains code you can inspect before running. Do not run on production checkouts. It does not use a database of up-to-date known fixes and does not auto-repair apps.

## 0.1.3: native artifact evidence inspection (experimental)

No installation or Gradle required. **Read-only**, local `.aar`, `.apk`, `.so` input.

```powershell
py -B .\inspect_native_artifact.py --self-test
py -B .\workbench.py inspect-native --artifact "C:\path\to\your\library.aar" --json
# Or for a final APK:
py -B .\workbench.py inspect-native --artifact "C:\path\to\your\app.apk" --json
```

Checks ELF `PT_LOAD` segment `p_align` against 16384 (16 KiB), and for an **APK only** checks stored `.so` ZIP payload offsets against 16384. Reports `.so` path/ABI, digest, and enclosing artifact digest. The container archive itself is observed; **which Maven dependency actually contributed an APK `.so` is NOT VERIFIED**. This is not a full ZIP integrity/signature/Play-release check. AAR ZIP packaging is not evidence of the final APK's ZIP alignment. APK packaging check is narrower than official `zipalign -c -P 16 -v 4 app.apk`. ELF alignment cannot verify Android runtime compatibility, other page-size assumptions or Play policy.

Return code 0 = narrow observed evidence or no `.so` found (**not** a release PASS), 2 = scoped 64-bit alignment attention, 3 = unknown/incomplete/not evaluated, 4 = file/input error. The experiment limits archive/member sizes and does not extract ZIP members to disk. Only read from trusted artifact files.

Sources:
- https://developer.android.com/guide/practices/page-sizes
- https://developer.android.com/tools/zipalign

**Acceptance still required:** analyze a real Android APK/AAR from an independently sourced reproducible case, compare manually with `llvm-objdump -p` and for APKs official `zipalign`, and establish which Gradle dependency contributed the native library. Synthetic ZIP/ELF tests alone do not qualify.


## 0.1.4 ABI/Prefab finding-scope correction

Actual FBJNI 0.7.0 AAR inspection showed 64-bit ELF files aligned to 16 KiB,
while 32-bit files were aligned to 4 KiB. Earlier versions raised
`ATTENTION_NATIVE_ALIGNMENT_EVIDENCE` from **all** ELF entries, conflating
32-bit `armeabi-v7a`/`x86` with 64-bit `arm64-v8a`/`x86_64`.

This version reports **32-bit ELF measurements as informational for the
64-bit Google Play 16 KiB gate**, distinguishes AAR `jni/` entries from
`prefab/` native build inputs, and separates `UNKNOWN`, `NOT_EVALUATED`,
and 64-bit alignment attention. The original p_align values remain
unchanged. **It does not claim that any AAR, SDK, or final APK is fully
compatible**, nor that `prefab/` entries are actually packaged in an APK.

`alignment_summary` includes counts for 64-bit, 32-bit, Prefab and JNI.
Use `--json` to preserve per-entry evidence.

No GitHub pushes, unrelated repository changes, automatic dependency
association, build/test certification or new artifact downloads are performed.

References: https://developer.android.com/guide/practices/page-sizes

For the independently Maven-checksummed user FBJNI 0.7.0 AAR, the reported
12 native archive entries were: 8 JNI and 4 Prefab; 6 x 64-bit (all
16KiB ELF-aligned) and 6 x 32-bit (4KiB aligned). Reclassification of
*the user-provided previous JSON* with this new rule gave
`OBSERVED_64BIT_SOURCE_ALIGNMENT_ONLY_NOT_RELEASE_CERTIFICATION`.
This is a **report-level reclassification**, not a claim that this release
has locally read the original `.aar` bytes. Rerun the original AAR locally.


## 0.1.5: isolated Gradle selected component → AAR → native `.so` bridge

**Scope:** Real Gradle dependency resolution in a generated, throwaway consumer project.
This **does not prove** the same dependency is selected by an existing RN/Expo application.
The original `inspect-native` and prior verification commands are unchanged.

From PowerShell after putting the new ZIP over the existing `RN_Upgrade_Workbench` folder:

```powershell
py -B .\native_provenance.py self-test
py -B .\workbench.py native-provenance-prepare `
  --artifact "$HOME\Downloads\fbjni-0.7.0.aar" `
  --coordinate "com.facebook.fbjni:fbjni:0.7.0" `
  --output-root "$HOME\Downloads\rn-native-fbjni-provenance-01"
```

Run a **real** Gradle artifact resolution in the staged project using the *already installed* Expo Gradle 9.4.1 wrapper. **Network is allowed**, because an artifact downloaded manually is not necessarily in Gradle's dependency cache; Gradle may download the same AAR and Maven metadata. Does not need Android SDK:

```powershell
& "$HOME\Downloads\rn-expo-sdk58-probe\android\gradlew.bat" `
  -p "$HOME\Downloads\rn-native-fbjni-provenance-01" `
  rnwbResolveAar --no-daemon --console=plain --max-workers=2 `
  2>&1 | Tee-Object -FilePath "$HOME\Downloads\rn-native-fbjni-provenance-01\gradle-resolution.log"
$GradleExit = $LASTEXITCODE
Write-Host "GRADLE_EXIT: $GradleExit"
```

Then assess the log against *both* on-disk byte digests and the recorded Gradle exit code:

```powershell
py -B .\workbench.py native-provenance-assess `
  --case "$HOME\Downloads\rn-native-fbjni-provenance-01\case.json" `
  --gradle-log "$HOME\Downloads\rn-native-fbjni-provenance-01\gradle-resolution.log" `
  --gradle-exit-code $GradleExit `
  --artifact "$HOME\Downloads\fbjni-0.7.0.aar" `
  --output "$HOME\Downloads\rn-native-fbjni-provenance-01\provenance-report.json"
```

The report establishes the requested Maven coordinate, the selected component identity **as emitted by the staged Gradle task**, exact AAR byte match against the original downloaded file and which `.so` members the AAR contains, including source-role and ABI. It reports `NOT_VERIFIED` for participation in the Expo app, APK/AAB packaging, native loading, device testing or Play readiness. This log is developer-run evidence, **not remote attestation**, and the Gradle build is not a sandbox. Use only the generated, trusted project. An absent artifact, changed source/hash or missing resolution record returns `INCONCLUSIVE`; do not convert that to a release PASS.

The code-level tests use *synthetic* Gradle log records; real resolution is only verified after running the Gradle command above. Never call it proof of Android production app usage.

Assessment requires explicit recorded Gradle exit code 0 and observed `BUILD SUCCESSFUL` log line, as well as the resolution marker, source integrity and file byte equality. Missing/failed task completion is **INCONCLUSIVE**, even when a marker appears.
