"""Rule R02: evaluate only justified AGP/Gradle facts against official minimums."""
from .models import Analysis, ResolvedFact, Finding, ResolutionStatus, RuleStatus
from .policy import load_agp_gradle_policy


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def compare_versions(actual: str, required: str) -> int:
    a, b = version_tuple(actual), version_tuple(required)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return (a > b) - (a < b)


def evaluate_agp_gradle(agp: ResolvedFact, gradle: ResolvedFact) -> Finding:
    policy = load_agp_gradle_policy()
    unresolved = [
        f"{fact.component}={fact.resolution_status.value}"
        for fact in (agp, gradle)
        if fact.resolution_status is not ResolutionStatus.RESOLVED
    ]
    if unresolved:
        return Finding(
            rule_id="R02_AGP_GRADLE_MINIMUM",
            status=RuleStatus.NOT_EVALUATED,
            message="R02 not evaluated because required facts are unresolved: " + ", ".join(unresolved),
            evidence_kind="deterministic_rule_not_evaluated",
            source_url=policy.source_url,
        )

    if agp.value is None or gradle.value is None:
        return Finding(
            rule_id="R02_AGP_GRADLE_MINIMUM",
            status=RuleStatus.NOT_EVALUATED,
            message="R02 not evaluated because a resolved fact has no value",
            evidence_kind="invalid_fact_state",
            source_url=policy.source_url,
        )

    series = ".".join(agp.value.split(".")[:2])
    required = policy.minimum_by_series.get(series)
    if required is None:
        return Finding(
            rule_id="R02_AGP_GRADLE_MINIMUM",
            status=RuleStatus.NOT_EVALUATED,
            message=f"AGP {agp.value} is outside policy snapshot coverage ({policy.snapshot_date})",
            evidence_kind="policy_evidence_not_available",
            source_url=policy.source_url,
        )

    if compare_versions(gradle.value, required) < 0:
        return Finding(
            rule_id="R02_AGP_GRADLE_MINIMUM",
            status=RuleStatus.BLOCKED,
            message=f"AGP {agp.value} requires Gradle >= {required}; resolved wrapper is {gradle.value}",
            evidence_kind="deterministic_official_minimum",
            source_url=policy.source_url,
            required_gradle=required,
        )

    return Finding(
        rule_id="R02_AGP_GRADLE_MINIMUM",
        status=RuleStatus.CHECKS_PASSED,
        message=f"AGP {agp.value} meets the Gradle minimum ({required}); resolved wrapper is {gradle.value}",
        evidence_kind="deterministic_official_minimum",
        source_url=policy.source_url,
        required_gradle=required,
    )


def analyze(project_root: str, agp: ResolvedFact, gradle: ResolvedFact) -> Analysis:
    return Analysis(
        project_root=project_root,
        agp=agp,
        gradle=gradle,
        finding=evaluate_agp_gradle(agp, gradle),
    )
