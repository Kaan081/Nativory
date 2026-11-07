# Safe Repair hardening pilot: cooperative lock + explicit wrapper recovery

**Status:** experimental. This patch builds on `SAFE_REPAIR_WRAPPER_PILOT.md` and retains the sole supported AGP 9.2.1 / Gradle 9.3.1 to Gradle 9.4.1 wrapper repair rule. The installed `rn-readiness` scanner is unaffected. **Use only disposable, trusted lab copies.**

## What changes

1. `execute` now holds a per-project, OS-backed, non-blocking advisory lock across planning precondition checks, backup, wrapper edit, Gradle `help` verification, and conditional wrapper rollback. The lock identifier is derived from the canonical project path and stored under the OS temporary directory. The lock file is deliberately retained. This excludes **cooperating Nativory commands** only: Git, IDEs, Gradle plugins and unrelated processes do not respect it.
2. `recover` inspects an approved v0.1 repair plan and its existing `.original.bak` sidecar. It requires an exact SHA-256 match for the saved original and reads the current wrapper. Read-only preview returns `RESTORABLE_WRAPPER_AFTER_IMAGE`, `ORIGINAL_ALREADY_PRESENT`, or a manual-recovery state.
3. With explicit `--restore --trust-disposable-project --approve <exact-plan-id>`, `recover` restores only the wrapper whose current bytes match the exact planned **postimage**, never an unexpected third-party version. It does **not** execute Gradle or certify the restored app.

The recovery tool may intentionally revert a *previously successful* v0.1 repair, because legacy reports do not have a durable completion journal. **Do not mistake a restorable postimage for proof of a crashed process.**

## Inspect an existing backup without writing the wrapper

From the Nativory repository, using the original `plan` from a prior approved lab repair (do not regenerate it) and its known `plan_id`:

```powershell
$tool = '.\tools\safe_repair\gradle_wrapper_repair.py'
$inspection = Join-Path $env:TEMP ("nativory-recovery-preview-" + [guid]::NewGuid().ToString('N') + '.json')
py -B $tool recover --plan $plan --approve $p.plan_id --report $inspection
$exit = $LASTEXITCODE
Get-Content $inspection -Raw | ConvertFrom-Json | Select-Object status,reason,current_sha256,original_sha256,new_sha256
Write-Host "RECOVERY PREVIEW EXIT: $exit"
```

Read-only preview does not write the target wrapper. If it reports `RESTORABLE_WRAPPER_AFTER_IMAGE`, this only means the target matches the planned repaired bytes and its backup matches the planned original bytes. It does **not** establish whether the earlier repair succeeded or crashed.

## Explicit restoration (only when it is really needed)

```powershell
$recoveryReport = Join-Path $env:TEMP ("nativory-recovery-" + [guid]::NewGuid().ToString('N') + '.json')
py -B $tool recover --plan $plan --approve $p.plan_id --restore --trust-disposable-project --report $recoveryReport
$exit = $LASTEXITCODE
Get-Content $recoveryReport -Raw | ConvertFrom-Json | Select-Object status,reason,current_sha256
Write-Host "RECOVERY EXIT: $exit"
```

`WRAPPER_RESTORED_FROM_BACKUP` means the original wrapper bytes were restored and read back with the expected hash. `ORIGINAL_ALREADY_PRESENT` means no restoration was necessary. Invalid or missing backups, modified target files, changed/invalid plans and concurrent repairs refuse or require manual review. Exit 0 for the **preview** command never means a restoration happened; inspect the JSON `status`.

## Coverage and limits

- Offline synthetic regression tests cover read-only preview, exact-byte restore, idempotence, altered target, invalid/missing backup, tampered plan, approval and explicit trust gates, and competing lock attempts. Existing v0.1 behavior is also regression-tested.
- The provided tests are not a real process-kill/power-loss test. There is no write-ahead transaction journal, no guaranteed crash-consistent fsync of directory metadata, and no automatic unattended recovery.
- File locks cannot prevent noncooperating edits; optimistic digest checks still have a possible race with external writers. Treat **all** filesystem content as untrusted on a hostile workspace.
- The wrapper JAR is not independently authenticated, and Gradle remains arbitrary executable project code. This does not undo other filesystem modifications, network activity, caches, compiled outputs, or partial builds.
- No `assembleDebug`, APK/AAB inspection, device verification, general Android upgrade, or production safety claim. The existing `help` check remains the only build-execution verification in `execute`.

The next gate is: verify Python + Gradle behavior on a **separate Windows lab copy**, simulate process interruption using a controlled fixture, review how to persist a durable transaction journal, and establish an external-change stress test before considering production use.
