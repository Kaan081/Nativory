# RN Upgrade Workbench alpha — integration and evidence scope

**Status:** Additive experimental module only. Existing `rn-readiness scan`, `trace-ndk`, and their JSON schema/exit contracts are unchanged. Does not modify published `main` or claim new release-readiness coverage.

## Components

- `tools/upgrade_workbench/workbench.py preflight`: exact historical Expo #50293 Kotlin-plugin signature, **not** a prediction of all upgrade compatibility.
- `replay-expo`: audit previously generated historical before/after log and source hashes, including explicitly reported Windows CRLF normalization.
- `verify --execute`: run **trusted, developer-specified commands** in separate directories, compare expected before failure and after evidence; no automatic repair.
- `inspect-native`: report `.so` ELF alignment, ABI/source role and narrow APK ZIP offset evidence; does **not** certify a release.
- `native-provenance-prepare` / `native-provenance-assess`: prepare a disposable Gradle consumer, then verify **that consumer's** Gradle-selected exact Maven component against AAR SHA-256 and embedded `.so` entries.

## Acceptance evidence (user executed, 2026-10-27)

| Case | Observed | Strongest conclusion | Critical missing proof |
|---|---|---|---|
| Expo #50293 | Controlled old 0.1.5 + KGP 2.3.20 failure; fixed 0.2.0 isolated Kotlin compile success; replay 11/11 | Historical regression and remedy consistent in isolated compiler tests | Full Expo APK or runtime |
| Reanimated #10544 | Gradle GString property probe and before/after scoped Gradle tasks: before exit 1, after 0, no source drift | `as? String` vs `CharSequence` semantics reproduced | Full Reanimated/NDK native build |
| FBJNI 0.7.0 | Maven downloaded AAR hash checked; 12 AAR native entries; 64-bit ELF aligned; generated consumer Gradle resolution PASS, provenance 16/16 | Isolated consumer selected `com.facebook.fbjni:fbjni:0.7.0` with exact AAR bytes | Installed Expo app resolution/usage; APK package alignment; device/Play acceptance |

**Evidence is from user-supplied terminal output, not CI in the `rn-readiness` repository.** Do not commit local logs, reports, downloaded binaries, paths from local machines or client data. Rerun CI and compare evidence on the integration branch.

## Developer checks

From repository root, with `pytest` installed:

```bash
python -m pytest -q tests/test_upgrade_workbench_alpha.py
python -B tools/upgrade_workbench/workbench.py self-test
python -B tools/upgrade_workbench/prepare_ndk_gstring_case.py --self-test
python -B tools/upgrade_workbench/inspect_native_artifact.py --self-test
python -B tools/upgrade_workbench/native_provenance.py self-test
```

The checks above are **synthetic** and make no network calls or Android builds. Gradle replay/verification against real artifacts remains a separate explicitly run acceptance step.

## Before feature-branch PR and later main promotion

1. Verify entire pre-existing test suite on Windows and Linux; no changes to existing CLI, packaging, R02/R03 policy, or JSON contracts.
2. Re-run both real Gradle accepted cases with pinned inputs and inspect artifacts; do not conflate historical log replay with new independent Gradle execution.
3. Independently compare ELF alignment with Android's `llvm-objdump`/`llvm-readelf`, and APK alignment with official `zipalign` when an APK exists.
4. Establish **actual installed application** Gradle dependency provenance; the isolated consumer must not be presented as application participation.
5. Track manual senior steps vs Workbench active work; no claim of measured time savings before this test.
6. Explicit maintainer review before any merge to `main`; no premature release or product/commercial readiness label.

## External reference

- https://github.com/expo/expo/issues/50293
- https://github.com/expo/expo/pull/50562
- https://github.com/software-mansion/react-native-reanimated/pull/10544
- https://developer.android.com/guide/practices/page-sizes
