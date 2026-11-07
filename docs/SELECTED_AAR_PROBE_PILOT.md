# Selected AAR probe v0.2 — experimental Gradle runtime evidence

**Status:** standalone developer-run Gradle init script, not part of installed `rn-readiness` / `nativory scan` CLI. Not a certified build/release check.

## Purpose

Given an **exact Maven coordinate** (group:module:version) and an Android app with a resolvable `:app` runtime classpath, report whether Gradle selected the AAR for that exact coordinate. If so, report its local filename, SHA-256 digest, byte size, and the `.so` archive entry paths (JNI **and** Prefab; paths do not prove APK packaging). Uses the Gradle resolved graph, not project text parsing. Does not perform ELF alignment inspection.

Task: `:app:nativoryTraceSelectedAar`; marker: `NATIVORY_SELECTED_AAR_V2:` followed by one JSON object. Properties: `-PnativoryCoordinate=group:module:version` and optional `-PnativoryConfiguration=debugRuntimeClasspath` (or `releaseRuntimeClasspath`). Run only against **trusted, disposable app checkouts**; Gradle executes project code and can download dependencies/update local caches/build artifacts. Init script does not intentionally edit app source files.

### Semantics

- `SCOPED_APP_SELECTED_AAR_OBSERVED`: exactly one requested AAR artifact was found in the selected resolved classpath; hash and entries are local measurements.
- `NOT_SELECTED`: exact coordinate not in resolved graph; `selected_component_versions` shows different selected versions for that module, if any. No AAR hash or native count is produced.
- `INCONCLUSIVE_SELECTED_COMPONENT_WITHOUT_AAR`: exact component was selected, but there was no AAR artifact observed.
- Some abnormal conditions (bad coordinate, missing configuration, multiple artifact matches, unreadable AAR, resolution failure) **fail the Gradle task**; they are not silently treated as success.

**Important:** Gradle exit 0 means a probe task completed, **not** that an AAR was selected. Consumers must inspect `status`, `requested_coordinate`, `selected_coordinate`, `scope`, and `reason`. `NOT_VERIFIED` fields are noncertification limitations, not downstream measurements.

## Real Expo 58 pilot observations — 2026-11-07

Test environment: Expo 58 / RN 0.88.1, AGP 9.2.1, Gradle 9.4.1; Windows PowerShell. Developer-observed outputs:

| Requested coordinate | Reported status | Selected versions | AAR native entries | Gradle exit |
|---|---|---|---:|---:|
| `com.facebook.react:react-android:0.88.0` | `NOT_SELECTED` | `0.88.1` | none (null) | 0 |
| `com.facebook.fbjni:fbjni:0.7.0` | `SCOPED_APP_SELECTED_AAR_OBSERVED` | `0.7.0` | 12 | 0 |

Earlier probe v0.1 also observed `com.facebook.react:react-android:0.88.1` AAR (`react-android-0.88.1-debug.aar`, 32 native entries) and `com.facebook.fbjni:fbjni:0.7.0` AAR (12 entries); **v0.2 is not yet independently re-run for react-android positive**. Provenance details and hashes are in the local testing logs, not uploaded to repository. The original AGP/Gradle policy scanner is unaffected.

## Repeatable local acceptance

Use the supplied `tools/selected_aar_probe/run_acceptance.ps1` with a disposable test app. It runs **three real Gradle queries**: different version selected, absent module, and positive selected AAR; it asserts the JSON contract and avoids interpreting Gradle exit 0 as verification. It is a local acceptance harness and **is not run by the existing Python CI matrix**.

```powershell
pwsh -NoProfile -File .\tools\selected_aar_probe\run_acceptance.ps1 `
  -ProjectAndroidRoot "$HOME\Desktop\nativory-rn-lab\NativoryExpo58\android" `
  -DifferentVersionCoordinate 'com.facebook.react:react-android:0.88.0' `
  -PositiveCoordinate 'com.facebook.fbjni:fbjni:0.7.0' `
  -ExpectedPositiveNativeEntries 12
```

For Windows PowerShell 5.1, replace `pwsh` with `powershell.exe`. Do not test against untrusted client apps; Gradle is **not a sandbox**. The output logs may include machine paths; inspect and scrub before sharing. The optional `-OutputDirectory` argument controls local log location.

## Boundaries and next steps

- App runtime classpath AAR selection is not proof that an `.so` enters the final APK/AAB, is loaded at runtime, or is associated with a root cause/fix.
- No third-party Maven checksum verification and no dependency-to-packaged-library cross-check yet.
- No repair, APK analysis, `zipalign`, Play certification, or measured engineering time savings.
- Next gate: test this script against an independently sourced app / additional AARs, then integrate a separate app-level provenance report with existing experimental native inspection only after contract and security review.
