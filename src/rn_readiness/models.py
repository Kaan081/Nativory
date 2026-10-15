"""Typed internal contract for evidence-backed state resolution.

Collectors discover evidence. Resolvers decide whether a fact is justified.
Policy evaluation consumes only resolved facts. Presentation does not recompute domain logic.
"""
from dataclasses import dataclass
from enum import Enum


class EvidenceScope(str, Enum):
    DECLARED = "declared"
    LOCAL_DEPENDENCY = "local_dependency"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNRESOLVED_DEPENDENCY_NOT_INSTALLED = "unresolved_dependency_not_installed"
    MALFORMED_EVIDENCE = "malformed_evidence"
    UNSUPPORTED_LAYOUT = "unsupported_layout"
    NO_EVIDENCE = "no_evidence"


class RuleStatus(str, Enum):
    CHECKS_PASSED = "checks_passed"
    BLOCKED = "blocked"
    NOT_EVALUATED = "not_evaluated"


class CheckStatus(str, Enum):
    CHECKS_PASSED = "checks_passed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evidence:
    value: str | None
    scope: EvidenceScope
    source: str
    resolution_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedFact:
    component: str
    value: str | None
    resolution_status: ResolutionStatus
    evidence: tuple[Evidence, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.resolution_status is ResolutionStatus.RESOLVED and self.value is not None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    status: RuleStatus
    message: str
    evidence_kind: str
    source_url: str | None = None
    required_gradle: str | None = None


@dataclass(frozen=True)
class Analysis:
    project_root: str
    agp: ResolvedFact
    gradle: ResolvedFact
    finding: Finding

    @property
    def status(self) -> CheckStatus:
        if self.finding.status is RuleStatus.CHECKS_PASSED:
            return CheckStatus.CHECKS_PASSED
        if self.finding.status is RuleStatus.BLOCKED:
            return CheckStatus.BLOCKED
        return CheckStatus.UNKNOWN
