# Nativory unified diagnosis — integration pilot

**Status: integration pilot, read-only, not release certification.** The new `nativory` CLI only composes the existing R02 AGP/Gradle minimum policy and the optional R03/R04 Windows log doctor. It does not add new compatibility rules, native code analysis, an Android build, a repair step or root-cause proof.

## Install and use

From a trusted checkout, after adding the new script entry point:

```powershell
py -m pip install -e '.[dev]'

# R02 only; R03/R04 explicitly NOT_EVALUATED
nativory scan 'C:\my-rn-app' --json

# R02 + R03/R04, supplying evidence from the SAME failed attempt
nativory scan 'C:\my-rn-app' `
  --build-log 'C:\logs\failed-build.log' `
  --cmake-cache 'C:\my-rn-app\android\app\.cxx\Debug\id\arm64-v8a\CMakeCache.txt' `
  --ninja-version 1.10.2 --json
```

Use real file paths. If no `--build-log` is supplied, native triage is **not run**. A CMake cache must come from the relevant failing build/module; if its evidence is not available, omit it and accept R03's `NOT_EVALUATED`. Ninja version comes from the operator, not an authenticated executable. Existing `rn-readiness` and `nativory-windows-doctor` commands retain their original interfaces.

## Result contract

`components.r02_agp_gradle` is the existing R02 report, unmodified. `components.windows_native_log_triage` contains the existing Windows doctor report if a log is supplied, otherwise an explicit `NOT_EVALUATED` skip record. The summary uses only these known statuses.

- `R02_INCOMPATIBLE`: a resolved AGP/Gradle minimum-version violation **only**; exit **2**.
- `REVIEW_REQUIRED`: R02 unresolved, no native log, or Windows findings other than `NO_MATCH`; exit **3**. A `SUSPECTED` clue **never** becomes a confirmed build error.
- `SCOPED_EVALUATIONS_COMPLETED`: R02 check passed and both R03/R04 reported `NO_MATCH`; exit **0**. **This is not a healthy-build or release pass.**
- Malformed input, unsupported evidence or unreadable files: exit **4** without emitting a partial JSON success report.

`android_build_verified`, `apk_aab_verified`, `runtime_verified` and `release_readiness_verified` are always false. A `NO_MATCH` result states only that a selected signature was absent. Aggregation never changes an R02 status or executes build scripts.

## Boundary and rollout

This is a composition-only first milestone. On a real user project, run the original R02 and Windows doctor commands independently and compare their component JSON to the unified output. Run the complete pytest suite plus Windows/Linux Python 3.10/3.13 CI packaging smoke checks before merging. Do not turn the summary into a blocking CI release gate until false positives/unknowns and exit-code expectations are reviewed.

This feature does **not** merge the separate AAR/ELF Workbench (draft PR #2), safe wrapper repair, or Gradle-selected-AAR probes. Those experimental modules have different input trust, execution and approval boundaries and should stay separate until individually validated.
