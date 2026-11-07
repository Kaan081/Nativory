# Expo 58 — R02 comparative acceptance

Date: 2026-11-07
Scope: AGP/Gradle minimum compatibility.

## Environment

- Expo: 58.0.23
- React Native: 0.88.1
- Applied AGP: 9.2.1
- Compatible Gradle: 9.4.1
- Platform: Windows 11

## Positive runtime validation

Nativory statically resolved AGP 9.2.1 and Gradle 9.4.1.

An independent Gradle init-script probe confirmed both values.
Gradle configuration succeeded.

## Controlled negative comparison

Changed the Expo Android Gradle wrapper declaration
temporarily from 9.4.1 to 9.3.1.

Nativory:
- Result: blocked
- Exit: 2
- Required Gradle: 9.4.1
- Reported wrapper: 9.3.1

Expo Doctor:
- Result: 20/20 checks passed
- Exit: 0
- No issue reported

Independent runtime confirmation:
- Directly launched Gradle 9.3.1 against the Expo app.
- Android Gradle Plugin rejected it:
  Minimum supported Gradle version is 9.4.1.
  Current version is 9.3.1.
- Gradle exit: 1

The original wrapper was restored after the static comparison.

## Interpretation

Nativory identified an AGP/Gradle incompatibility that
Expo Doctor did not report in this controlled experiment.

This demonstrates complementary coverage for one R02 case.
It does not establish general superiority over Expo Doctor,
real-world customer demand, or overall Android build readiness.

Runtime command output was observed locally; raw logs are
not included in this repository.
