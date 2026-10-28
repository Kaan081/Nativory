# Nativory — Native Upgrade Evidence

Evidence-backed native dependency tracing and scoped upgrade verification for React Native / Android.

**Core principle:** *Evidence before certainty.*

Nativory is intentionally conservative: if it cannot justify a toolchain fact from supported evidence, it returns an unresolved state and does **not** convert uncertainty into a compatibility failure.

> **The goal is not to minimize UNKNOWN. The goal is to minimize unjustified certainty.**

This repository is an engineering prototype, not a release certification product. It does **not** claim automatic repairs, universal compatibility, production release certification, full APK/AAB readiness, validated customer-app fixes, comprehensive known-fix intelligence, or proven engineer time savings.

## Two capability layers in this repository

### A. Installed read-only scanner (`rn_readiness`)

The published Python package (`rn-readiness-spike` on PyPI metadata; import path `rn_readiness`) exposes a narrowly scoped, read-only CLI:

- **`nativory`** and legacy **`rn-readiness`** invoke the same entry point.
- **Current scanner scope:** one rule only — **R02: Android Gradle Plugin (AGP) ↔ Gradle minimum compatibility**.

See [Install](#install-from-source) and [CLI](#cli) below.

### B. Experimental native upgrade evidence workbench (`tools/upgrade_workbench/`)

Separately implemented scripts and workflows (historically labeled **RN Upgrade Workbench**) provide additive, experimental evidence tooling. **None of this is invoked by the installed `nativory` / `rn-readiness` console command** — run Workbench scripts explicitly from `tools/upgrade_workbench/` when needed.

Capabilities in that layer include:

- native `.so` / AAR / APK inspection (`inspect-native`);
- Gradle AAR provenance experiments (`native-provenance-*`);
- FBJNI 0.6.0 → 0.7.0 published ELF comparison and fail-closed cross-source Evidence Bridge;
- controlled Expo SDK 58 app-selected before/after experiment;
- historical Expo #50293 and Reanimated #10544 isolated replay cases.

Documentation and limitations for prior experiments are preserved in [`tools/upgrade_workbench/README.md`](tools/upgrade_workbench/README.md), [`docs/UPGRADE_WORKBENCH_ALPHA.md`](docs/UPGRADE_WORKBENCH_ALPHA.md), [`docs/FBJNI_EVIDENCE_BRIDGE.md`](docs/FBJNI_EVIDENCE_BRIDGE.md), and the pilot evaluation guide [`docs/NATIVORY_PILOT.md`](docs/NATIVORY_PILOT.md). Machine-readable markers such as `RNWB_*` and bridge statuses like `SCOPED_CROSS_SOURCE_EVIDENCE_VERIFIED_NOT_APP_FIX` remain stable compatibility contracts.

### Verified CI evidence (scoped experiments, not product certification)

These GitHub Actions runs document **demonstrated** evidence on the integration branch. They are **not** permanent downloadable archives: workflow artifacts expire (typically within days); run logs and committed code remain, but binary evidence must be re-fetched while artifacts still exist.

| Experiment | CI run |
|---|---|
| Expo app dependency provenance (Gradle-selected FBJNI AAR) | [actions/runs/40575645915](https://github.com/Kaan081/rn-readiness/actions/runs/40575645915) |
| Published FBJNI 0.6.0 / 0.7.0 ELF pair inspection | [actions/runs/40648144209](https://github.com/Kaan081/rn-readiness/actions/runs/40648144209) |
| Fail-closed cross-source Evidence Bridge | [actions/runs/40652357978](https://github.com/Kaan081/rn-readiness/actions/runs/40652357978) |
| Controlled same-Expo-app before/after AAR experiment | [actions/runs/40652924782](https://github.com/Kaan081/rn-readiness/actions/runs/40652924782) |

Future product capabilities (unified CLI, broader rules, customer-app validation, time-savings claims) are **not** implied by these runs or by the installed R02 scanner alone.

## Why the scanner exists

Modern React Native apps can declare AGP indirectly. A root `build.gradle` may contain a versionless dependency such as:

```gradle
classpath("com.android.tools.build:gradle")
```

In supported modern layouts, the scanner follows static provenance instead of guessing:

```text
android/settings.gradle
→ @react-native/gradle-plugin
→ local installed plugin
→ gradle/libs.versions.toml
→ AGP version
```

The resulting fact is then evaluated against a frozen official AGP → minimum Gradle policy table.

## What the scanner does today

- resolves explicit AGP declarations in a deliberately small set of Groovy/Kotlin forms;
- resolves literal React Native `includeBuild(...@react-native/gradle-plugin...)` provenance;
- recognizes a narrow production-observed `require.resolve(...) → includeBuild(...)` React Native pattern without executing Node or Gradle;
- reads the Gradle wrapper version statically;
- preserves evidence source, scope, and resolution path;
- refuses to choose precedence when credible evidence conflicts;
- emits deterministic JSON;
- does not modify the inspected repository.

## What the scanner does **not** do

- no generic Gradle/Groovy/Kotlin interpreter;
- no arbitrary Node or Gradle execution;
- no Android build or AAB inspection;
- no NDK/Kotlin/target-SDK rules in the installed CLI yet;
- no auto-repair;
- no claim of broad React Native ecosystem coverage;
- no claim that static local dependency evidence proves the effective runtime Gradle build graph.

## Domain model

```text
Evidence[]
    ↓
Fact Resolver
    ↓
ResolvedFact
    ↓
Policy Evaluation
    ↓
Finding
    ↓
Decision
```

```text
Evidence:
  value
  scope
  source
  resolution_path

ResolvedFact:
  component
  value | null
  resolution_status
  evidence[]
```

Initial evidence scopes:

- `declared`
- `local_dependency`

Resolution states:

- `resolved`
- `conflicting_evidence`
- `unresolved_dependency_not_installed`
- `malformed_evidence`
- `unsupported_layout`
- `no_evidence`

Policy invariant:

```text
resolution_status == resolved
→ evaluate R02

anything else
→ NOT_EVALUATED
```

## Install from source

Python 3.10+ is required.

```bash
python -m venv .venv
python -m pip install -e .
```

For development:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

- **`nativory`** — new supported console alias (same behavior as below).
- **`rn-readiness`** — legacy console command; remains supported.
- **`rn_readiness`** — unchanged Python import path (`import rn_readiness`).
- **`rn-readiness-spike`** — unchanged distribution/package name on install metadata; version **0.1.3** for this pilot review is branding-only — do not treat a locally rebuilt wheel as a substitute for any previously distributed `0.1.3` artifact without a new version id.

## CLI

```bash
nativory scan path/to/react-native-repo --json
# backward-compatible alias:
rn-readiness scan path/to/react-native-repo --json
```

Return codes:

- `0` — scoped R02 check passed
- `2` — resolved facts violate R02 policy
- `3` — unknown / not evaluated
- `4` — invalid input or explicit I/O error

Example fact:

```json
{
  "component": "agp",
  "value": "9.2.1",
  "resolution_status": "resolved",
  "evidence": [
    {
      "value": "9.2.1",
      "scope": "local_dependency",
      "source": "node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml",
      "resolution_path": [
        "android/settings.gradle dynamic require.resolve includeBuild",
        "@react-native/gradle-plugin",
        "gradle/libs.versions.toml"
      ]
    }
  ]
}
```

## Validation status

v0.1.3 has been exercised against:

- a normally package-manager-installed React Native 0.87.1 app;
- a derived installed-app fixture using the supported dynamic `require.resolve(...) → includeBuild(...)` wiring;
- a **frozen 20-repository stress corpus** selected before scanner results were inspected.

Observed acceptance results:

| Check | Result |
|---|---:|
| Manual AGP vs scanner on installed RN 0.87.1 | `9.2.1 == 9.2.1` |
| Dynamic installed-layout acceptance | PASS |
| Frozen corpus false AGP resolutions observed | `0` |
| Manual agreement on corpus-resolved cases | `2 / 2` |
| Deterministic corpus scans | `20 / 20` |
| Read-only corpus scans | `20 / 20` |

The unchanged v0.1.3 corpus rerun still resolves only `2 / 20` repository snapshots because many snapshots intentionally contain no installed `node_modules`, and several entries are libraries/framework monorepos rather than normal installed applications. **That number is not presented as product coverage.**

See [`docs/VALIDATION.md`](docs/VALIDATION.md) and [`docs/corpus/R02_CORPUS_FREEZE_v1.md`](docs/corpus/R02_CORPUS_FREEZE_v1.md).

## Policy provenance

R02 uses a versioned snapshot of the official Android Gradle Plugin minimum-Gradle compatibility table stored in:

```text
src/rn_readiness/knowledge/agp_gradle_minimums.json
```

Official reference: <https://developer.android.com/build/releases/about-agp>

This is a **minimum-version compatibility rule only**, not full Android build compatibility.

## Legacy naming

The GitHub repository may still appear as `rn-readiness`; PyPI/distribution id `rn-readiness-spike`; and internal module `rn_readiness`. These identifiers are preserved for backward compatibility. User-facing product name is **Nativory**.

## License

MIT. See [`LICENSE`](LICENSE).
