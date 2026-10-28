# Nativory pilot evaluation guide

**Product:** Nativory — Native Upgrade Evidence
**Principle:** Evidence before certainty.

This guide is for a senior engineer deciding whether the **current repository state** is worth deeper investment. It is not a release certification checklist and not a one-command native repair workflow.

## What you can evaluate today

| Layer | What it is | Integrated into `nativory` CLI? |
|---|---|---|
| **Installed scanner** | Read-only R02 AGP ↔ Gradle minimum check (`rn_readiness` package) | **Yes** — `nativory` and `rn-readiness` are the same entry point |
| **Experimental workbench** | Scripts under `tools/upgrade_workbench/` (native inspect, Gradle provenance, FBJNI bridge, historical replays) | **No** — run Python files explicitly; never assume `nativory scan` covers them |

## Installed scanner (offline, no Gradle)

Requires: Python 3.10+, a local React Native Android tree to inspect (your own clone or fixture).

```powershell
python -m pip install -e .
nativory scan path\to\react-native-app --json
# legacy alias (identical behavior):
rn-readiness scan path\to\react-native-app --json
```

- **No network** required for the scan itself.
- **Does not** run Gradle, Node, or modify the target repo.
- **Exit codes:** `0` passed R02; `2` policy violation; `3` unknown / not evaluated; `4` input/I/O error.
- **JSON contract:** `schema_version` `0.2`, scope `R02_AGP_GRADLE_MINIMUM_ONLY`; human text reports still use the legacy header `=== RN Readiness / R02 ===`.

Interpretation:

- **`unknown` / `NOT_EVALUATED`** — insufficient or conflicting static evidence; **not** a failed compatibility verdict.
- **`blocked`** — resolved AGP and Gradle facts contradict the frozen minimum policy table.
- Limitations in JSON `limitations[]` are part of the scoped conclusion, not boilerplate.

## Experimental workbench (separate commands)

From repository root. See also [`tools/upgrade_workbench/README.md`](../tools/upgrade_workbench/README.md).

**No Gradle / no network (synthetic self-tests):**

```powershell
py -B tools/upgrade_workbench/workbench.py self-test
py -B tools/upgrade_workbench/inspect_native_artifact.py --self-test
py -B tools/upgrade_workbench/native_provenance.py self-test
py -B tools/upgrade_workbench/prepare_ndk_gstring_case.py --self-test
py -B -m pytest -q tests/test_upgrade_workbench_alpha.py tests/test_acceptance_bridge.py
```

**Local artifact read-only (no Gradle):** `inspect-native` on a trusted `.aar`, `.apk`, or `.so` you already possess.

**Gradle / network may be required:** `verify --execute`, `native-provenance-assess`, disposable consumer builds, and replay of real upgrade cases. Treat Gradle as **trusted-code execution** with cache and filesystem side effects. Failures must map to `UNKNOWN_*` / `BLOCKED_*` — do not reinterpret as success.

**Evidence Bridge (offline on downloaded CI artifacts):**

```powershell
python tools/upgrade_workbench/acceptance_bridge.py --app-dir ... --pair-dir ... --output report.json
```

Success status is only `SCOPED_CROSS_SOURCE_EVIDENCE_VERIFIED_NOT_APP_FIX` (not an app-level fix proof).

## Verified CI evidence (demonstrated facts, expiring artifacts)

These runs support **scoped** conclusions documented in-repo. Artifact ZIPs expire; logs and committed code remain.

| Topic | Run |
|---|---|
| Expo app Gradle-selected FBJNI AAR provenance | https://github.com/Kaan081/rn-readiness/actions/runs/40575645915 |
| Published FBJNI ELF pair | https://github.com/Kaan081/rn-readiness/actions/runs/40648144209 |
| Cross-source Evidence Bridge | https://github.com/Kaan081/rn-readiness/actions/runs/40652357978 |
| Same-Expo-app controlled before/after AAR | https://github.com/Kaan081/rn-readiness/actions/runs/40652924782 |

Re-running CI after your branch changes requires a **push**; do not claim new CI until that happens.

## Security and confidentiality

- Do **not** upload client production repos, credentials, private logs, or proprietary APK/AAB to this evaluation.
- Use local clones you are allowed to hold, or public fixtures.
- Workbench Gradle modes can execute build logic and write caches — use disposable directories only.
- Do not commit machine-specific paths, tokens, or customer artifacts into the repository.

## Interpreting scoped PASS vs gaps

| Signal | Meaning |
|---|---|
| `checks_passed` / scoped bridge PASS statuses | Evidence consistent **within the stated scope** only |
| `UNKNOWN`, `NOT_EVALUATED`, `INCONCLUSIVE_*` | Missing evidence, conflict, or unavailable upstream artifact — **fail closed** |
| `SCOPED_*_NOT_APP_FIX` suffix | Explicitly **not** customer-app repair or store release acceptance |
| Workbench `ATTENTION_*` alignment flags | Narrow native observation; not Play policy or full APK certification |

## What remains unproven

- End-to-end native upgrade repair in a customer production app from a single CLI command.
- Universal compatibility across the React Native ecosystem.
- Measured engineer time savings vs AI-assisted manual Gradle debugging (track both **active tool time** and **senior interpretation time** in your pilot; no claim is made here).
- Runtime, device, Play release, and full APK/AAB readiness from static scanner output alone.
- Permanent retention of CI artifact bytes (artifacts expire).

## Pilot time-savings assessment (suggested)

1. Pick one real AGP/Gradle ambiguity on an app you may inspect locally (not client-confidential if policy forbids).
2. Time manual trace + Gradle docs vs `nativory scan --json` for **R02 only**.
3. Separately, if native upgrade evidence is in scope, time manual `readelf`/Maven checksum work vs Workbench `inspect-native` / bridge scripts on **your own** artifacts.
4. Record where the tools stopped with `UNKNOWN` — that is expected behavior, not a defect to “fix” in the pilot.

## Packaging note (pilot review)

Distribution metadata remains `rn-readiness-spike` **0.1.3**. A wheel rebuilt locally for branding review must **not** be redistributed as a replacement for any previously sent `0.1.3` wheel; ship a new version when publishing a distinct build.
