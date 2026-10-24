# NDK Provenance Corpus Freeze v1

Frozen: 2026-10-24
Tool commit: `d763ad6` on `feature/ndk-provenance-trace`
Selection rule: ten SHAs taken from `R02_CORPUS_FREEZE_v1` (same pins). Do not remove failures.

| # | Repository | Frozen commit | Scan root | Notes |
|---|---|---|---|---|
| 1 | react-native-community/template | `fe29a9ad1344af52e787cd0fa3a5b707d631bb85` | `template/` | |
| 2 | mattermost/mattermost-mobile | `726cd9865d4b2c0040853e9c364fa6365791dbb1` | repo root | |
| 3 | MetaMask/metamask-mobile | `0c61213714554680d5421af337b72f89e0f72f7d` | repo root | sparse `android/` checkout when full clone fails |
| 4 | zulip/zulip-mobile | `d7cf6da79b4b9467e240b42f24330e97390a8aff` | repo root | |
| 5 | react-native-maps/react-native-maps | `39c6fd177d6c91ea087fcf083fd484f2499b6ea8` | repo root | |
| 6 | software-mansion/react-native-reanimated | `ca7c3fbc2879c976e19e41bf2c6206042becf154` | repo root | partial checkout on Windows (long paths) |
| 7 | react/react-native | `a443ea471c2d7676e6bc42222ddf8a960944ac42` | repo root | |
| 8 | RocketChat/Rocket.Chat.ReactNative | `a08ab04b98021737c119aea9978c85fdecc4c6cc` | repo root | |
| 9 | jitsi/jitsi-meet | `8a85912a0424ac2dd159853c242630bd11760701` | repo root | |
| 10 | BlueWallet/BlueWallet | `55df7d2c4385080b42b39333ad3b2faf5d01400e` | repo root | |

Corpus checkouts live under `%TEMP%\\rn_readiness_ndk_corpus_v1` (machine-local).
All runs: `trace-ndk` with `node_modules` absent unless noted — **no installed dependency NDK declarations** in this pass.

Machine-readable spec: [`NDK_CORPUS_FREEZE_v1.json`](NDK_CORPUS_FREEZE_v1.json)
Run output: [`NDK_CORPUS_RESULTS_v1.json`](NDK_CORPUS_RESULTS_v1.json)
Manual literal review: [`NDK_CORPUS_MANUAL_REVIEW_v1.md`](NDK_CORPUS_MANUAL_REVIEW_v1.md)
