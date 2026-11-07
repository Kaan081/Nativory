# Safe Repair Pilot v0.1: bounded Gradle wrapper transaction

**Status: experimental, not included in the installed CLI. Do not run on customer or production app source.** This pilot demonstrates one *guarded* edit on a user-owned disposable React Native/Expo app, not general Android repair.

## Exact scope

Only one source-proven mismatch is supported:

- Resolved AGP: **9.2.1** (Nativory's existing offline R02 scanner)
- Resolved Gradle wrapper: **9.3.1**
- R02 state: **blocked**, minimum required Gradle: **9.4.1**
- The `distributionUrl` must exactly point to `https\://services.gradle.org/distributions/gradle-9.3.1-{bin,all}.zip` (with literal or escaped `:`).
- When the existing `distributionSha256Sum` is present, it must match the **official 9.3.1** `-bin` or `-all` checksum. If absent, the proposed repair inserts the **official 9.4.1** checksum.
- The only file edited is `android/gradle/wrapper/gradle-wrapper.properties`. Other wrapper files (including the JAR) are not regenerated.

Official sources: [AGP vs Gradle](https://developer.android.com/build/releases/about-agp), [Gradle 9.3.1 and 9.4.1 distribution checksums](https://gradle.org/release-checksums/), [Gradle wrapper security](https://docs.gradle.org/current/userguide/best_practices_security.html).

Any unresolvable AGP/Gradle facts, conflicting or unsupported layouts, unrecognized existing checksum, custom distribution URL, changed preimage, pre-existing backup, or unexpected file structure produce a refusal/manual review. Nothing is changed during `plan`.

## Workflow

1. **Plan:** statically scan with the already-shipped Nativory R02 scanner, inspect the exact wrapper properties, and write a JSON plan including the immutable preimage digest, proposed postimage digest, unified diff, and an approval ID. Does not execute Gradle or mutate the project.
2. **Explicit approval:** review the JSON diff and supply the **exact** `plan_id`. The tool recalculates the plan from the actual project immediately before applying; stale or tampered plans are rejected.
3. **Execute:** after `--trust-disposable-project` acknowledgement, persist the original wrapper bytes in an exclusive local backup, atomically replace only the wrapper properties, rerun the R02 scanner, and execute `android/gradlew[.bat] help --no-daemon --console=plain` in the disposable app (timeout 240s).
4. **Rollback on failure:** restore the exact original bytes **only if the wrapper still contains the bytes the tool wrote**. If another actor changed it, refuse to overwrite and report `MANUAL_RECOVERY_REQUIRED` with the saved backup path. All results stay scoped to `Gradle help`, not a full app build.

The process is *not* a general transaction: Gradle and its plugins may write caches or build outputs, download files, invoke arbitrary code, or mutate other files. The tool does **not** undo these. It is unsafe to run Gradle from an untrusted project, even if the wrapper properties edit itself is tightly controlled. `gradle-wrapper.jar` should also be independently validated against official Gradle checksums before executing a newly supplied project.

## Commands (PowerShell; from local Nativory repo)

```powershell
cd "$HOME\Desktop\nativory-git"
py -m pytest -q tests/test_gradle_wrapper_safe_repair.py
py -m pytest -q

$project = Join-Path $HOME 'Desktop\nativory-rn-lab\NativoryExpo58'
$tool = '.\tools\safe_repair\gradle_wrapper_repair.py'
$plan = Join-Path $env:TEMP ("nativory-wrapper-plan-" + [guid]::NewGuid().ToString('N') + '.json')

py -B $tool plan --project $project --output $plan
$p = Get-Content $plan -Raw | ConvertFrom-Json
$p | Select-Object status,reason,agp,gradle,required_gradle,plan_id
$p.diff
```

The already repaired Expo 58 lab should produce `NO_REPAIR_NEEDED`; do not downgrade the working app merely to make the output look impressive. To test `execute`, first establish a **separate disposable lab app** with exactly this **controlled mismatch**, using an out-of-repository immutable backup of its original wrapper. Do not run `execute` without reviewing the proposed diff.

For a `READY_FOR_APPROVAL` plan on a trusted disposable app only:

```powershell
$report = Join-Path $env:TEMP ("nativory-wrapper-verify-" + [guid]::NewGuid().ToString('N') + '.json')
py -B $tool execute --plan $plan --approve $p.plan_id --trust-disposable-project --report $report
$exit = $LASTEXITCODE
if (Test-Path $report) {
  Get-Content $report -Raw | ConvertFrom-Json |
    Select-Object status,reason,gradle_help_exit,original_backup_path,release_certified
}
Write-Host "REPAIR EXIT: $exit"
```

### Exit/status meanings

- `plan` exit 0: either `READY_FOR_APPROVAL` or `NO_REPAIR_NEEDED`, **not** a repair success.
- `plan` exit 2: `MANUAL_REVIEW_REQUIRED` (file still unchanged).
- `execute` exit 0: `VERIFIED_SCOPED_GRADLE_HELP_ONLY` (R02 passed and Gradle `help` exit 0).
- `execute` exit 2: failed verification, rolled back, or manual recovery required. Inspect JSON and backup.
- Exit 4: invalid input/plan/file/output. Never interpret this as an application compatibility result.

## Honest boundaries and next gates

- No automatic AGP upgrades, React Native dependency upgrades, ELF rebuild, 16 KiB APK/AAB alignment certification, `assembleDebug` verification, device testing, release signing, or client app fix.
- The Gradle `help` task checks configuration and Gradle execution only, not a complete build; the pilot does **not** prove a downstream failure is fixed.
- Persistent backup supports crash recovery, but automatic rollback cannot guarantee recovery after process termination, power loss, concurrent edits, or external Gradle side effects.
- The code uses an atomic single-file replace and hash-based optimistic checks, **not** filesystem locking or a hostile-workspace security boundary.
- The wrapper JAR is not automatically authenticated; `--trust-disposable-project` is an explicit **user trust decision**, not attestation.
- Initial acceptance is **synthetic unit tests**. Real Expo Gradle `help` acceptance must still be performed separately and the outcome recorded before calling this a tested repair capability.
- Before considering a PR merge, test a real controlled failure, a success, a forced `Gradle help` failure with rollback, and verification of bytes restored exactly, then add CI coverage for the pure repair logic.
