# FBJNI cross-source evidence bridge (Nativory experimental)

Part of the Nativory native upgrade evidence workbench (`tools/upgrade_workbench/`). Historical logs may refer to “Workbench” and `RNWB_*` markers; those contracts are unchanged.

Scope: combine evidence from a CI-generated Expo SDK 58 application’s selected
`debugRuntimeClasspath` FBJNI AAR and two published Maven AAR native inspections.
Do **not** equate this with a fix executed in the same application.

Run against downloaded, unmodified GitHub Actions artifact contents:

```bash
python3 tools/upgrade_workbench/acceptance_bridge.py \
  --app-dir .bridge/app --pair-dir .bridge/pair \
  --output evidence/scoped-fix-evidence-bridge.json
```

When a mismatch is found, the command creates an `INCONCLUSIVE_EVIDENCE_GAP_OR_CONTRADICTION`
JSON report and exits 2. It only returns success for
`SCOPED_CROSS_SOURCE_EVIDENCE_VERIFIED_NOT_APP_FIX`.

Checks:
- prior Gradle graph exited zero and both Gradle logs indicate success;
- exact app-selected FBJNI Maven coordinate, no contradictory scope claims;
- published AAR checksums agree with Workbench output;
- app selected AAR hash equals the published positive AAR hash;
- 64-bit native entry paths and header alignments agree between independent
  `readelf` measurements and Workbench parser on both published versions;
- the same published 64-bit library paths are observed before and after.

The workflow **pins** source GitHub Action run IDs and commit SHAs, checks both
runs concluded successfully, and downloads only their recorded evidence. It does
not rerun Gradle, download an Android SDK or produce an APK. Artifacts retained
7 days; an expired upstream artifact is an inconclusive/unavailable run, not PASS.

Limitations: Evidence is self-consistent, not a cryptographically attested build;
the before AAR was **not selected in the Expo app**; no same-app fix execution,
APK ZIP alignment, runtime, Play release or engineering-time savings verified.
Do not change the CLI/report names or graduate this to main until reviewed.
