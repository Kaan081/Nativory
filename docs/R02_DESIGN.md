# R02 design notes

## Scope

R02 asks one question:

> Given a resolved AGP version and a resolved Gradle wrapper version, does the wrapper satisfy the official minimum Gradle requirement for that AGP series?

Fact extraction, fact resolution, and policy evaluation are separate layers.

## Evidence model

```text
Evidence:
  value
  scope
  source
  resolution_path
```

`scope` records provenance, not confidence.

Current scopes:

- `declared`
- `local_dependency`

## Resolved fact model

```text
ResolvedFact:
  component
  value | null
  resolution_status
  evidence[]
```

Current resolution states:

- `resolved`
- `conflicting_evidence`
- `unresolved_dependency_not_installed`
- `malformed_evidence`
- `unsupported_layout`
- `no_evidence`

## Conflict rule

If multiple credible pieces of evidence contain different values and the scanner has no justified effective-precedence rule:

```text
value = null
resolution_status = conflicting_evidence
R02 = NOT_EVALUATED
```

No precedence is guessed.

## Local React Native plugin provenance

Literal supported path:

```text
settings.gradle(.kts)
→ includeBuild("../node_modules/@react-native/gradle-plugin")
→ local installed package
→ gradle/libs.versions.toml
```

Narrow dynamic supported path:

```text
settings.gradle
→ recognized require.resolve('@react-native/gradle-plugin/package.json', ...)
→ includeBuild(...)
→ conventional local installed package
→ gradle/libs.versions.toml
```

The scanner does not execute the embedded expression. If the installed package cannot be located safely and unambiguously, the fact remains unresolved.

## Policy gate

```text
resolution_status == resolved
→ evaluate

anything else
→ NOT_EVALUATED
```

This prevents missing or conflicting AGP evidence from becoming a false compatibility failure.
