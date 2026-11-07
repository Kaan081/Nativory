# R02 installed RN 0.87.1 runtime acceptance

Date: 2026-11-07
Scope: AGP / Gradle minimum compatibility only.

## Test environment

- React Native: 0.87.1
- Installed React Native Gradle Plugin: 0.87.1
- Android Gradle Plugin: 9.2.1
- Gradle: 9.4.1
- JDK: 17
- Platform: Windows 11

## Positive acceptance

Nativory resolved AGP 9.2.1 and Gradle 9.4.1.
Scanner status: checks_passed.
Scanner exit: 0.

A Gradle init-script probe confirmed:
- Applied AGP: 9.2.1
- Running Gradle: 9.4.1
- Gradle configuration: BUILD SUCCESSFUL

## Negative acceptance

A derived static fixture retained AGP 9.2.1 and
changed the declared wrapper to Gradle 9.3.1.

Nativory status: blocked.
Scanner exit: 2.
Required Gradle: 9.4.1.

Separately, the installed RN application was configured
using a direct Gradle 9.3.1 launcher.

Android Gradle Plugin rejected the configuration:
"Minimum supported Gradle version is 9.4.1.
Current version is 9.3.1."

Gradle exit: 1.
The original application wrapper remained at 9.4.1.

## Limits

- One installed React Native application was validated.
- The negative case was controlled, not a production failure.
- This validates Gradle configuration compatibility, not APK builds.
- Broad ecosystem coverage has not been established.
- Runtime logs were retained locally; this document records
  observed results rather than embedding raw machine-specific logs.
