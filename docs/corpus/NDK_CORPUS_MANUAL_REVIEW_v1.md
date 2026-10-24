# NDK corpus manual literal review (v1)

Reviewer: agent manual file inspection at frozen SHAs (2026-10-24).
Legend: **MATCH** | **FALSE POSITIVE** | **AMBIGUOUS**

All repos: `node_modules_present=false` → **no dependency (`installed_dependency`) NDK declarations** in this pass.

---

## 1. react-native-community/template — `fe29a9ad…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | literal | `28.2.13676358` | **MATCH** (`ndkVersion = "28.2.13676358"`) |
| project | `android/app/build.gradle` | root_inherited | — | **MATCH** (`ndkVersion rootProject.ext.ndkVersion`) |

Attention: none.

---

## 2. mattermost/mattermost-mobile — `726cd986…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | literal | `27.1.12297006` | **MATCH** |
| project | `android/app/build.gradle` | root_inherited | — | **MATCH** |

Attention: none.

---

## 3. MetaMask/metamask-mobile — `0c612137…` (sparse `android/`)

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | literal | `27.1.12297006` | **MATCH** |
| project | `android/app/build.gradle` | root_inherited | — | **MATCH** |
| project | `android/build.gradle` | root_inherited | — | **AMBIGUOUS** — matches `subproject.android.ndkVersion = rootProject.ext.ndkVersion` propagation loop, not the root `ext` block literal |

Attention: none.

---

## 4. zulip/zulip-mobile — `d7cf6da7…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | literal | `24.0.8215888` | **MATCH** |

Attention: none.

---

## 5. react-native-maps/react-native-maps — `39c6fd17…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | root_inherited | — | **MATCH** (line after `hasProperty("ndkVersion")` guard; guard line correctly ignored) |

Note: `hasProperty` line not emitted as declaration.

Attention: none.

---

## 6. software-mansion/react-native-reanimated — `ca7c3fbc…`

**Trace:** empty declarations (no evidence at scanned paths).

**Manual:** NDK wiring exists under `apps/*/android/` and `packages/*/android/` but **outside** current project scan roots (`android/` at repo root only). Classified as **no-evidence (scope limit)**, not parser error.

Attention: none.

---

## 7. react/react-native — `a443ea47…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `build.gradle.kts` (repo root) | unsupported_expression | — | **MATCH** — `val ndkVersion by extra(...)`; no literal claimed |

Other `ndkVersion` uses in `packages/react-native/ReactAndroid/*.kts` use `hasProperty` guards — correctly not reported from those lines.

Attention: none.

---

## 8. RocketChat/Rocket.Chat.ReactNative — `a08ab04b…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | literal | `27.1.12297006` | **MATCH** |
| project | `android/app/build.gradle` | root_inherited | — | **MATCH** |

Attention: none.

---

## 9. jitsi/jitsi-meet — `8a85912a…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | literal | `27.1.12297006` | **MATCH** |

**Not reported:** `android/sdk/build.gradle` `ndkVersion rootProject.ext.ndkVersion` — file not in scan list (coverage gap).

Attention: none.

---

## 10. BlueWallet/BlueWallet — `55df7d2c…`

| Owner | Source | Kind | Value | Manual |
|---|---|---|---|---|
| project | `android/build.gradle` | literal | `28.2.13676358` | **MATCH** |
| project | `android/app/build.gradle` | root_inherited | — | **MATCH** |

Attention: none.

---

## Summary

| Metric | Count |
|---|---|
| Repos in corpus | 10 |
| Literal hits manually reviewed | 7 |
| MATCH | 8 |
| FALSE POSITIVE | 0 |
| AMBIGUOUS | 1 (MetaMask subproject propagation line) |
| Dependency literals | 0 (no `node_modules`) |
| Attention signals | 0 |
