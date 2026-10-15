# Changelog

## 0.1.3 — 2026-10-14

- add narrow static recognition of production-observed React Native `require.resolve(...) → includeBuild(...)` plugin wiring;
- preserve local dependency provenance for the resolved plugin catalog;
- keep missing dependency, conflict, malformed evidence, and unsupported-layout states conservative;
- ship a 75-test public regression suite after replacing third-party source snapshots with synthetic minimal fixtures;
- validate the dynamic path against a real installed React Native 0.87.1 dependency tree;
- rerun the unchanged frozen 20-repository corpus with 0 observed false AGP resolutions, 2/2 manual agreement on resolved cases, 20/20 deterministic scans, and 20/20 read-only scans.

## 0.1.2

- introduce explicit `Evidence[]` and `ResolvedFact` domain models;
- separate provenance from resolution state;
- add modern React Native local Gradle Plugin catalog provenance;
- add conservative unresolved/conflicting semantics and deterministic JSON reporting.
