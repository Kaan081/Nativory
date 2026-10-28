# Nativory — Native Upgrade Evidence

Evidence-backed native dependency tracing and scoped upgrade verification for React Native / Android.

**Current main-branch capability:** the original offline, read-only R02 AGP/Gradle scanner. Its supported command is still `rn-readiness`.

**Experimental development:** native artifact inspection, FBJNI verification, Evidence Bridge and the new `nativory` CLI alias are in [Draft PR #2](https://github.com/Kaan081/Nativory/pull/2). They are not yet merged into `main`.

**Legacy compatibility:** the Python package remains `rn_readiness` and the distribution remains `rn-readiness-spike`.

**Principle:** Evidence before certainty.

**Current scope:** one rule only — **R02: Android Gradle Plugin (AGP) ↔ Gradle minimum compatibility**.

The current scanner is intentionally conservative: if it cannot justify a toolchain fact from supported evidence, it returns an unresolved state and does **not** convert uncertainty into a compatibility failure.

> **The goal is not to minimize UNKNOWN. The goal is to minimize unjustified certainty.**

## Why this exists

Modern React Native apps can declare AGP indirectly. A root `build.gradle` may contain a versionless dependency such as:

```gradle
classpath("com.android.tools.build:gradle")
```

In supported modern layouts, The current scanner follows static provenance instead of guessing:

```text
android/settings.gradle
→ @react-native/gradle-plugin
→ local installed plugin
→ gradle/libs.versions.toml
→ AGP version
```

The resulting fact is then evaluated against a frozen official AGP → minimum Gradle policy table.

## What it does today

- resolves explicit AGP declarations in a deliberately small set of Groovy/Kotlin forms;
- resolves literal React Native `includeBuild(...@react-native/gradle-plugin...)` provenance;
- recognizes a narrow production-observed `require.resolve(...) → includeBuild(...)` React Native pattern without executing Node or Gradle;
- reads the Gradle wrapper version statically;
- preserves evidence source, scope, and resolution path;
- refuses to choose precedence when credible evidence conflicts;
- emits deterministic JSON;
- does not modify the inspected repository.

## What it does **not** do

- no generic Gradle/Groovy/Kotlin interpreter;
- no arbitrary Node or Gradle execution;
- no Android build or AAB inspection;
- no NDK/Kotlin/target-SDK rules yet;
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

## CLI

```bash
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

## Project status

This repository is an engineering prototype, not a release certification product. The current useful question is whether evidence-backed tracing like this saves real maintenance time on production React Native apps.

## License

MIT. See [`LICENSE`](LICENSE).
