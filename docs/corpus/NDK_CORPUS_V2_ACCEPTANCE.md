# NDK Provenance Corpus V2 ? Acceptance Record

Date: 2026-10-24

## Evidence status

**PASS: Independent, source-only CLI replay.**
Ten repositories were checked at their pinned Git SHAs. All ten
`trace-ndk --json` executions succeeded. Total: **15 declarations**.

Tool revision: `3ff9e8635ca69700f49c12c74a5a59fd7c569d7e`.

All ten scans used checkouts with verified SHA, origin and clean
working tree. V1 freeze and results were preserved unchanged.

This is **not** evidence of full native Android builds, Gradle
evaluation, effective NDK selection or installed dependency coverage.

## Changes from V1

All ten frozen repository SHAs remain identical.

- **Reanimated:** The scan root changed from the monorepo root to
  `apps/fabric-example`, a valid Android application. Declarations
  changed from 0 to 2: one literal and one root-inherited.
- **MetaMask:** Declarations changed from 3 to 2. The omitted line
  `subproject.android.ndkVersion = rootProject.ext.ndkVersion` is
  real subproject configuration. Its omission is a parser coverage
  boundary, not proof that the configuration is irrelevant.
- **React Native:** Declarations changed from 1 to 0. The source
  still contains `val ndkVersion by extra(...)` in `build.gradle.kts`.
  Zero reported declarations must not be interpreted as absence
  of NDK configuration.

All ten records have updated explanatory `limitations` text.
That presentation change was recorded separately from declaration
differences. Attention signals remained unchanged.

## Reproduction scope and limitations

The V2 snapshot was produced by independently invoking the same
`rn_readiness trace-ndk <scan-root> --json` CLI for each pinned
checkout, with explicit SHA/origin/clean-worktree validation.

The React Native source was scanned from a clean sparse staging
checkout at `react__react-native__stage_a443ea47`. Jitsi used the
verified replacement at `jitsi__jitsi-meet__retry`. The invalid
original checkouts were not deleted.

`trace_ndk_corpus_only.py` still defaults to the V1 manifest and
its own checkout-selection rules. Automated V2 replay through that
entry point has **not** been accepted. Replaying V2 elsewhere
requires reproducing the verified checkout selection and scan roots.

All source-only checkouts reported `node_modules_present=false`.
No installed-dependency declarations or native build acceptance
are claimed.

## Decision

V2 evidence snapshot: **GO to preserve on a separate documentation
branch**.

Automatic V2 runner replay: **NOT VERIFIED**.

New feature expansion and main-branch merge: **HOLD pending their
independent acceptance gates**.
