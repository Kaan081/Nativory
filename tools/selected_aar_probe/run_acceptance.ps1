# Local Gradle runtime acceptance for Nativory selected-AAR probe v0.2.
# Run ONLY on a disposable/trusted Android app; Gradle executes project build logic.
# This is NOT a CI test. Gradle can download dependencies and update caches/build outputs.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectAndroidRoot,
    [Parameter(Mandatory = $true)]
    [string]$PositiveCoordinate,
    [Parameter(Mandatory = $true)]
    [string]$DifferentVersionCoordinate,
    [string]$AbsentCoordinate = 'com.example.nativory:module-that-does-not-exist:0.0.0',
    [int]$ExpectedPositiveNativeEntries = -1,
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'nativory_selected_aar_probe.init.gradle'
$gradlew = Join-Path $ProjectAndroidRoot 'gradlew.bat'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) { throw 'PROBE_NOT_FOUND' }
if (-not (Test-Path -LiteralPath $gradlew -PathType Leaf)) { throw 'GRADLE_WRAPPER_NOT_FOUND' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $env:TEMP 'nativory-aar-v02-acceptance' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$cases = @(
    @{ name='different-version'; coordinate=$DifferentVersionCoordinate; expected='NOT_SELECTED'; reason='DIFFERENT_VERSION_SELECTED' },
    @{ name='absent-module'; coordinate=$AbsentCoordinate; expected='NOT_SELECTED'; reason='MODULE_NOT_IN_RESOLVED_CONFIGURATION' },
    @{ name='positive'; coordinate=$PositiveCoordinate; expected='SCOPED_APP_SELECTED_AAR_OBSERVED'; reason='EXACT_AAR_SELECTED_AND_OBSERVED' }
)

Push-Location $ProjectAndroidRoot
try {
    foreach ($case in $cases) {
        $log = Join-Path $OutputDirectory ("aar-v02-{0}.log" -f $case.name)
        & $gradlew ':app:nativoryTraceSelectedAar' `
            '--init-script' $scriptPath `
            ("-PnativoryCoordinate={0}" -f $case.coordinate) `
            '--no-daemon' '--console=plain' *> $log
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Get-Content -LiteralPath $log -Tail 45 | Out-Host
            throw ("GRADLE_EXIT_NONZERO:{0}:{1}" -f $case.name, $exitCode)
        }

        $records = @(Get-Content -LiteralPath $log | Where-Object { $_ -match '^NATIVORY_SELECTED_AAR_V2:' })
        if ($records.Count -ne 1) {
            Get-Content -LiteralPath $log -Tail 45 | Out-Host
            throw ("EXPECTED_ONE_RECORD:{0}:found={1}" -f $case.name, $records.Count)
        }
        $record = $records[0].Substring('NATIVORY_SELECTED_AAR_V2:'.Length) | ConvertFrom-Json
        if ($record.schema_version -ne 'nativory-selected-aar-probe-0.2' -or
            $record.scope -ne 'APP_RESOLVED_RUNTIME_AAR_ONLY' -or
            $record.configuration -ne 'debugRuntimeClasspath' -or
            $record.requested_coordinate -ne $case.coordinate -or
            $record.status -ne $case.expected -or
            $record.reason -ne $case.reason) {
            throw ("CONTRACT_MISMATCH:{0}:status={1}:reason={2}" -f $case.name, $record.status, $record.reason)
        }
        foreach ($key in @('actual_apk_packaging','runtime_loading','third_party_checksum_match','root_cause_or_fix')) {
            if ($record.$key -ne 'NOT_VERIFIED') { throw ("SCOPE_OVERCLAIM:{0}:{1}" -f $case.name, $key) }
        }
        $parts = $case.coordinate.Split(':')
        if ($case.name -eq 'positive') {
            if ($record.selected_coordinate -ne $case.coordinate -or
                -not ($record.artifact_sha256 -match '^[0-9a-f]{64}$') -or
                $record.artifact_bytes -le 0 -or
                $record.native_entry_count -ne @($record.native_entry_paths).Count -or
                $record.native_entry_count -lt 0 -or
                @($record.selected_component_versions).Count -ne 1 -or
                @($record.selected_component_versions)[0] -ne $parts[2]) {
                throw 'POSITIVE_EVIDENCE_INVALID'
            }
            if ($ExpectedPositiveNativeEntries -ge 0 -and
                $record.native_entry_count -ne $ExpectedPositiveNativeEntries) {
                throw ("NATIVE_COUNT_MISMATCH:expected={0}:actual={1}" -f $ExpectedPositiveNativeEntries, $record.native_entry_count)
            }
        } else {
            if ($null -ne $record.selected_coordinate -or
                $null -ne $record.artifact_sha256 -or
                $null -ne $record.native_entry_count -or
                @($record.native_entry_paths).Count -ne 0 -or
                @($record.selected_component_versions) -contains $parts[2]) {
                throw ("NEGATIVE_EVIDENCE_INVALID:{0}" -f $case.name)
            }
            if ($case.name -eq 'different-version' -and @($record.selected_component_versions).Count -lt 1) {
                throw 'DIFFERENT_VERSION_NOT_EXPLAINED'
            }
            if ($case.name -eq 'absent-module' -and @($record.selected_component_versions).Count -ne 0) {
                throw 'ABSENT_MODULE_SHOULD_HAVE_NO_VERSIONS'
            }
        }
        $summary = "{0}: exit={1} status={2} versions=[{3}] native={4}" -f `
            $case.name, $exitCode, $record.status, `
            (@($record.selected_component_versions) -join ','), $record.native_entry_count
        Write-Host $summary
    }
} finally {
    Pop-Location
}
Write-Host 'NATIVORY_SELECTED_AAR_V02_LOCAL_ACCEPTANCE: PASS (3 cases)'
