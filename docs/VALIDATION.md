# R02 validation — v0.1.3

Validation date: 2026-10-14
Scope: **R02 only — AGP ↔ Gradle minimum compatibility**

## Acceptance summary

R02 v0.1.3 is frozen at the current rule scope.

Observed gates:

```text
installed React Native app acceptance: PASS
literal local-plugin provenance:       PASS
dynamic require.resolve provenance:    PASS
false AGP resolutions observed:        0
manual agreement on resolved corpus:   2/2
corpus deterministic:                  20/20
corpus read-only:                       20/20
broad layout coverage:                 NOT CLAIMED
```

The governing principle remains:

> **The goal is not to minimize UNKNOWN. The goal is to minimize unjustified certainty.**

## Installed React Native acceptance

A normally created, package-manager-installed React Native 0.87.1 application was inspected on Windows.

Manual evidence:

```text
node_modules/@react-native/gradle-plugin present: true
local plugin catalog AGP:               9.2.1
Gradle wrapper:                         9.4.1
```

Scanner result:

```text
AGP:               9.2.1
resolution_status: resolved
Gradle:            9.4.1
R02:               checks_passed
```

The Git worktree was clean before and after scanning.

This establishes that the scanner reproduced the declaration bundled with the installed React Native Gradle Plugin. It does **not** prove the effective runtime Gradle build graph.

## Dynamic `require.resolve(...) → includeBuild(...)` acceptance

The frozen v0.1.2 corpus exposed production layouts in which `settings.gradle` computes the React Native Gradle Plugin path through a narrow Node `require.resolve(...)` expression before passing it to `includeBuild(...)`.

v0.1.3 recognizes only this specific wiring shape. It does not execute Node, Gradle, Groovy, or Kotlin.

A derived installed-app acceptance fixture was created from the real installed RN 0.87.1 app by replacing literal `includeBuild` wiring with the supported dynamic form while reusing the same installed `node_modules` read-only.

Observed scanner result:

```text
resolution path:
  android/settings.gradle dynamic require.resolve includeBuild
  → @react-native/gradle-plugin
  → gradle/libs.versions.toml

AGP:               9.2.1
resolution_status: resolved
Gradle:            9.4.1
R02:               checks_passed
```

## Frozen 20-repository corpus

The corpus was frozen before scanner results were inspected. Exact repositories and commit SHAs are recorded in [`corpus/R02_CORPUS_FREEZE_v1.md`](corpus/R02_CORPUS_FREEZE_v1.md).

### v0.1.2 baseline

```text
resolved:                             2 / 20
unresolved_dependency_not_installed: 6 / 20
unsupported_layout:                  4 / 20
no_evidence:                         8 / 20
false resolved values observed:      0
manual agreement on resolved:        2 / 2
deterministic JSON:                  20 / 20
read-only:                           20 / 20
```

### v0.1.3 unchanged-corpus rerun

```text
resolved:                             2 / 20
unresolved_dependency_not_installed: 8 / 20
unsupported_layout:                  2 / 20
no_evidence:                         8 / 20
false resolved values observed:      0
manual agreement on resolved:        2 / 2
deterministic JSON:                  20 / 20
read-only:                           20 / 20
```

The important change is not a higher resolved count. Mattermost/MetaMask-style dynamic wiring moved from `unsupported_layout` to `unresolved_dependency_not_installed` in source-only snapshots: the mechanism is recognized, but the scanner correctly refuses to infer the bundled AGP when `node_modules` is absent.

## Manual validation of the two resolved corpus cases

### `zulip/zulip-mobile`

Frozen commit: `d7cf6da79b4b9467e240b42f24330e97390a8aff`

```text
manual AGP:   7.2.2
scanner AGP:  7.2.2
Gradle:       7.3.3
agreement:    yes
```

### `react-native-maps/react-native-maps`

Frozen commit: `39c6fd177d6c91ea087fcf083fd484f2499b6ea8`

```text
manual AGP:   8.7.2
scanner AGP:  8.7.2
Gradle:       8.14.3
agreement:    yes
```

Applicability caveat: this repository is a native library and its AGP declaration is used for its standalone Android project. That does not establish a downstream application's effective AGP. This is a reminder that **fact resolution and policy applicability are separate concerns**.

## What the validation supports

- Supported evidence paths can resolve AGP without inventing a value.
- Missing installed dependencies remain unresolved.
- Conflicting credible values remain conflicts; no precedence is guessed.
- Unsupported layouts remain explicit rather than silently misread.
- JSON output is deterministic in the frozen corpus.
- Corpus scans are read-only.

## What it does not support

- broad real-world React Native layout coverage;
- runtime Gradle build-graph truth;
- Android build success or release readiness beyond R02;
- downstream app policy applicability for every library/monorepo corpus entry;
- auto-remediation claims.
