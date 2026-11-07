# Selected AAR → native ELF inspector bridge (experimental)

This **offline** bridge joins two already-generated machine reports:

1. `NATIVORY_SELECTED_AAR_V2:` from the Gradle-selected-AAR v0.2 probe currently on `main`.
2. `rn-upgrade-native-evidence-0.2` JSON from the standalone `inspect_native_artifact.py` in the experimental `experiment/expo58-graph` branch.

It requires exact matching SHA-256, artifact name, byte size, native entry count **and complete native archive path set**, and cross-checks evidence scope and ELF assessment. A mismatch or incomplete 64-bit ELF evidence produces `INCONCLUSIVE` (exit 2). Missing/invalid input returns exit 4. A *scoped* match returns exit 0; **even then, Android APK/AAB packaging, release readiness, runtime behavior, third-party checksum verification and application repair are all unverified.** `ATTENTION_64BIT_ALIGNMENT_EVIDENCE` is reported as attention, not a release pass.

This code does not execute Gradle, fetch network resources, open the AAR, or independently re-hash artifact bytes. It is a consistency check across developer-run reports, not cryptographic attestation of their producers. The Gradle-side task itself can execute trusted project code; run that separately in disposable test apps.

## Run on the already-collected Expo FBJNI reports (PowerShell)

```powershell
$repo = Join-Path $HOME 'Desktop\nativory-git'
$log = Join-Path $env:TEMP 'nativory-aar-v02-acceptance\aar-v02-positive.log'
$inspection = Join-Path $env:TEMP 'nativory-fbjni-native-inspection.json'
$output = Join-Path $env:TEMP 'nativory-fbjni-native-bridge.json'
if (!(Test-Path $log) -or !(Test-Path $inspection)) { throw 'Missing local evidence input' }
if (Test-Path $output) { throw 'Output already exists; choose a new path or archive your prior report' }
py -B "$repo\tools\selected_aar_probe\bridge_native_evidence.py" `
  --probe-log "$log" `
  --inspection-json "$inspection" `
  --output "$output"
$exit = $LASTEXITCODE
Write-Host "BRIDGE EXIT: $exit"
if (Test-Path $output) {
  $r = Get-Content $output -Raw | ConvertFrom-Json
  $r | Select-Object status,reason,coordinate,native_entry_count,elf_assessment_status
}
```

## Local Python regression

```powershell
py -m pytest -q tests/test_selected_aar_native_bridge.py
py -m pytest -q
```

No Gradle CI coverage is added by this kit. Existing Python tests can run in the standard Python CI matrix after merging. Source provenance and hashes in logs are developer-run evidence; do not publish logs containing private or machine-specific paths without review.

## Evidence-consistency hardening

The bridge also checks each classified 64-bit JNI/Prefab ELF entry against its
recorded `PT_LOAD` segment alignment flags, recalculates the 16 KiB alignment
predicate from the recorded segment numbers, and rejects an aggregate status or
64-bit entry count that contradicts those records. This does **not** authenticate
the records, read the original bytes again, or certify APK packaging.
