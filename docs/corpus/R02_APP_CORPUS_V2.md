# R02 application corpus V2 — measurement protocol

**Status:** measurement harness only; no new verified builds or accuracy claims.

## Objective

This is an **application-focused subset** of the already frozen 20-repository V1
corpus. We preserve original revisions and include eight production-app cases
plus one template control. It is deliberately **not** a replacement for the
original corpus, and it is **not** yet a corpus of installed/built applications.

The primary question is: when dependencies are present in a pinned real React
Native application, does the scanner identify **the actually applicable AGP
version** without unjustified certainty?

## Predeclared cases

All IDs, URLs, and exact commits are in `R02_APP_CORPUS_V2.json`; they come from
`R02_CORPUS_FREEZE_v1.md`. These were selected for **application identity**,
not because the scanner would return RESOLVED. The `rn-template` case is a
**template control**, excluded from the application-only summary denominator.

## Three distinct evidence layers

1. **Static declaration observation:** files such as `android/build.gradle`,
   `settings.gradle`, local plugin catalogs, and the Gradle wrapper. A manual
   reading can be recorded as `manual_declaration`. This does **not** establish
   what Gradle actually applied.
2. **Runtime Gradle verification:** a genuinely observed AGP version from the
   evaluated application build, recorded with method `gradle_runtime` and a
   human-reviewable log/source reference. Do not upgrade a declaration to
   runtime truth based only on scanner agreement. Record the exact command,
   environment, Gradle properties and any injected init scripts in the log.
3. **Build/cook outcome:** separate build evidence. **Not measured** by this
   harness; do not claim an Android build works just because R02 passes.

The harness **never invokes Gradle, Node, package managers, installers or the
network**. An operator must inspect and execute untrusted repository build
scripts **only** inside an approved sandbox/isolated environment. Do not pass
personal credentials into third-party apps. Gradle plugins and scripts are
executable code.

## Running the scanner safely

From a development installation of Nativory (`pip install -e '.[dev]'`):

```powershell
py scripts/app_corpus_v2.py --plan
```

Place exact pinned Git checkouts in a directory **outside Nativory**:

```text
C:\nativory-corpus\
  zulip-mobile\
  mattermost-mobile\
  ...
```

Each folder name must match its `id`, and `git rev-parse HEAD` must equal the
manifest's full SHA. **Do not change the manifest SHA to match an arbitrary
checkout**; do a separately frozen V3 experiment if you need fresher repos.

To scan (no install or build):

```powershell
py scripts/app_corpus_v2.py --manifest docs/corpus/R02_APP_CORPUS_V2.json --checkouts C:\nativory-corpus --output C:\nativory-results\app-v2.json
```

A partially populated corpus still writes a result with `missing_checkout`,
`revision_mismatch` or `scan_root_missing` states. It returns exit code `2`
until all selected checkouts are available; **partial runs are not acceptance**.
It also returns `2` for a mismatch against supplied manual or runtime
truth. These assertions still depend on human evidence review. Output cannot
be placed inside the checkout tree. No checkout is created or modified.

The `node_modules_present` field records only directory presence, **not** proof
of a complete install. A snapshot with no installed dependencies is useful for
testing honest UNKNOWN behavior, **not** for estimating installed-app coverage.

## Optional human-verified ground truth

Create a separate local file (e.g. `C:\nativory-results\truth.json`), following
this schema. The example is intentionally empty; **no runtime evidence has been
supplied yet**:

```json
{"schema_version": 1, "facts": []}
```

Each fact added later requires **all** of:

```json
{
  "id": "zulip-mobile",
  "commit": "d7cf6da79b4b9467e240b42f24330e97390a8aff",
  "method": "manual_declaration",
  "agp": "7.2.2",
  "evidence_ref": "reviewed android/build.gradle at frozen SHA"
}
```

This illustrates **manual declaration evidence**, not runtime confirmation.
A future `gradle_runtime` fact must cite a real Gradle execution log from the
same revision and a controlled environment. Supply with `--truth PATH`.

An AGP value differing from manually read source is a
`manual_declaration_mismatch`; a differing actually observed Gradle version is
`gradle_runtime_mismatch`. The two are **not equivalent**.

## Initial independent source inspection (not scanner/build results)

Four of the pinned source snapshots were inspected directly:

| Case | Gradle wrapper (source) | AGP mechanism visible in source | Runtime truth? |
| --- | --- | --- | --- |
| Zulip Mobile | 7.3.3 | explicit `com.android.tools.build:gradle:7.2.2` | **No** |
| Mattermost Mobile | 9.0.0 | dynamic `require.resolve` with a versionless AGP classpath | **No** |
| MetaMask Mobile | 9.3.1 | dynamic `require.resolve` with a versionless AGP classpath | **No** |
| Expensify App | 9.3.1 | literal RN Gradle plugin `includeBuild` with versionless AGP classpath | **No** |

All observations are from the **manifest's frozen commit**, not from today's
HEAD. No installed `node_modules` or effective Gradle plugin version was
independently checked for these four cases in this V2 preparation.

## Required next measurement gates

- Source-only scan: all nine frozen checkouts. Keep all UNKNOWN reasons.
- Installed-app scan: prepare at least **three** cases using documented,
  reproducible package-manager installs in isolated environments. Record exact
  package-manager/lockfile and installed dependency state. Do not calculate
  an installed-app resolution rate from source-only snapshots.
- Independently capture Gradle-applied AGP for those cases. Gradle initialization
  can execute arbitrary project code; handle as untrusted. Report unavailable
  ground truth as **NOT_VERIFIED**, never as a match.
- Compare same-revision source-only vs installed results and classify each
  newly resolved/unknown case. Only then prioritize additional parser patterns.

## Notes on scope

The R02 rule checks **minimum AGP–Gradle compatibility**, not build success,
release certification or all Android SDK/NDK compatibility. Gradle supports
nonstandard catalogs and plugin-management resolution strategies; simply
recognizing a plugin string is not proof of the effective applied version.

References:
- https://docs.gradle.org/current/userguide/version_catalogs.html
- https://docs.gradle.org/current/userguide/plugins_intermediate.html
- https://reactnative.dev/docs/integration-with-existing-apps
- https://docs.expo.dev/versions/latest/sdk/build-properties/
