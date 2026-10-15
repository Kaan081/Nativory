# R02 AGP Corpus Freeze v1

Frozen before running the v0.1.2 scanner against corpus snapshots.

Selection rule: keep the exact 20 repositories and commit SHAs below even if the scanner fails to resolve them. Do not remove failures from the corpus.

| # | Repository | Frozen branch | Frozen commit | Scan root | Intended family |
|---|---|---|---|---|---|
| 1 | react-native-community/template | main | fe29a9ad1344af52e787cd0fa3a5b707d631bb85 | `template/` | modern RN template |
| 2 | react/react-native | main | a443ea471c2d7676e6bc42222ddf8a960944ac42 | repo root | RN framework monorepo / version catalog |
| 3 | mattermost/mattermost-mobile | main | 726cd9865d4b2c0040853e9c364fa6365791dbb1 | repo root | production OSS RN app |
| 4 | RocketChat/Rocket.Chat.ReactNative | develop | a08ab04b98021737c119aea9978c85fdecc4c6cc | repo root | production OSS RN app |
| 5 | Expensify/App | main | f3dc42e57a823f834120cd9f6557b61f04b70953 | repo root | production OSS RN app / monorepo |
| 6 | MetaMask/metamask-mobile | main | 0c61213714554680d5421af337b72f89e0f72f7d | repo root | production OSS RN app |
| 7 | rainbow-me/rainbow | develop | e406e093f1b7afbd212023dcc52e14d6a3bce230 | repo root | production OSS RN app |
| 8 | jitsi/jitsi-meet | master | 8a85912a0424ac2dd159853c242630bd11760701 | repo root | production OSS RN app |
| 9 | BlueWallet/BlueWallet | master | 55df7d2c4385080b42b39333ad3b2faf5d01400e | repo root | production OSS RN app |
| 10 | zulip/zulip-mobile | main | d7cf6da79b4b9467e240b42f24330e97390a8aff | repo root | production OSS RN app / legacy-modern transition |
| 11 | expo/expo | main | 01d7e772cf4d369720eb62f7b2a5110ac323d9bc | repo root | Expo monorepo |
| 12 | software-mansion/react-native-reanimated | main | ca7c3fbc2879c976e19e41bf2c6206042becf154 | repo root | RN native library / custom Gradle |
| 13 | software-mansion/react-native-gesture-handler | main | f5da9afed1bd1d6c5e51a30c3a595955fdd49444 | repo root | RN native library / custom Gradle |
| 14 | react-native-maps/react-native-maps | master | 39c6fd177d6c91ea087fcf083fd484f2499b6ea8 | repo root | RN native library / example app |
| 15 | wix/react-native-navigation | master | 1de39e0d5da34c077b4998b9f0cbe972e770a464 | repo root | RN native library / custom integration |
| 16 | invertase/react-native-firebase | main | c1471450b06019dd718f59a8a1b4c5bf941cc1bb | repo root | RN native library monorepo |
| 17 | react-native-device-info/react-native-device-info | master | 06a9ed6d700cab9c55b363e6fa944ee8e5605745 | repo root | RN native library / example app |
| 18 | lottie-react-native/lottie-react-native | master | 2d60a7b0b6782d1f606991654880b993566dba6d | repo root | RN native library monorepo |
| 19 | wcandillon/react-native-skia | main | 20b4de3a60f1719d9a87af36140af91b81c13380 | repo root | RN native library / custom Gradle |
| 20 | reown-com/react-native-examples | main | 28ec79e02f9dac3ce817cd4944757df79d92d6eb | repo root | RN example-app collection / monorepo |

## Predeclared success metrics

- False resolved values: 0
- Agreement on resolved cases: 100%
- Coverage: measured, not optimized

A low resolution rate is acceptable in this first corpus if unresolved states are explicit and justified. Any false resolved AGP value is a red flag.
