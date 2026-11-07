# Windows Native Doctor — R03/R04 diagnostic pilot

**Status: experimental, offline and read-only.** This is a separate log triage command, not an additional R02 policy gate, automatic fix, Android build, or release certification.

The pilot was motivated by a controlled Expo 58 / React Native 0.88.1 Windows test: the native linker error stopped recurring after moving NDK 27.1.12297006 to a whitespace-free location and rebuilding; an app codegen `ninja: error: mkdir(...)` path measured 261 characters with Ninja 1.10.2; using CMake 3.31.6/Ninja 1.12.1 and refreshed caches preceded a successful `assembleDebug`. **Those changes also refreshed generated state, so causality is not fully isolated.** Do not advertise these correlations as guaranteed repairs.

## Run

```powershell
# From your Nativory repository root, after installing in editable mode:
py -m pip install -e '.[dev]'
py -m pytest -q tests/test_windows_native_doctor.py

# Choose the build log and CMakeCache.txt belonging to the SAME failed attempt.
# Replace the example paths with your real project paths.
nativory-windows-doctor --project 'C:\nv' `
  --build-log 'C:\path\to\failed-build.log' `
  --cmake-cache 'C:\nv\android\app\.cxx\Debug\some-id\arm64-v8a\CMakeCache.txt' `
  --ninja-version 1.10.2 --json
```

A `CMakeCache.txt` can instead be inside `node_modules/react-native-screens/android/.cxx/` or `node_modules/react-native-worklets/android/.cxx/`. Supply an effective cache **from the failing module and build attempt**, not a newer cache produced after repairs. Multiple `--cmake-cache` flags are supported; conflicting effective NDK locations lead to `NOT_EVALUATED`. The cache file(s) must be inside `--project`.

`--ninja-version` is a *caller-supplied assertion*, not something the program executes or authenticates. The doctor extracts the working directory from a recognized `-C ^ "..."` line in the failed Gradle log. If the log omits it, supply `--ninja-dir 'C:\nv\android\app\.cxx\Debug\id\arm64-v8a'`. Do not reuse a working directory from a different failure.

Windows PowerShell 5.1 native redirection (`*> build.log`) produces UTF-16 LE
with a byte-order mark (BOM). The doctor accepts UTF-8, UTF-8 BOM, UTF-16 LE
BOM, and UTF-16 BE BOM logs. BOM-less UTF-16 and malformed encodings are
refused instead of silently returning `NO_MATCH`.

## Rules and states

- **R03_WINDOWS_NDK_PATH**: compares selected `ld.lld` C++ runtime undefined-symbol signatures with the effective NDK path recorded in a supplied CMake cache. `android/local.properties` is read only for separately identified *declared* NDK evidence; it never establishes the effective path.
- **R04_NINJA_LONG_PATH**: requires a `ninja: error: mkdir(...)` signature and a recoverable Ninja working directory; computes a Windows path length without accessing the generated tree. If the path reaches 260 characters and an explicitly provided Ninja version is earlier than 1.12.0, emits `SUSPECTED`.

`SUSPECTED` means a pattern fits the observed failure, **not that it proves the root cause**; `RISK_SIGNAL` is weaker; `NOT_EVALUATED` means evidence is missing, ambiguous, or not sufficient; and `NO_MATCH` means the configured signature was not observed, **not a successful build**. Exit `0` means the analysis ran, regardless of finding; exit `4` means bad or unreadable input.

## Safety and limitations

- Reads at most 8 MB of log and 1 MB of each CMake cache, with up to 16 caches; rejects symlinked input files and out-of-project cache paths.
- Never executes Gradle, Ninja, CMake, the build scripts, or network code; never modifies project files; emits no raw logs or absolute personal paths.
- Windows drive letter paths and Gradle `-C` command output are the supported initial layout. Other forms return `NOT_EVALUATED` rather than guessing.
- No long-path policy modification, SDK copying, `ndk.dir` edits, `gradle.properties` edits, or rebuilds are performed.
- Not tested across broad production projects; no basis for claims about installed Ninja, all RN versions, root cause certainty, APK runtime, or Play Store readiness.
