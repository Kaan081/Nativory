"""Presentation boundary only: no new domain evaluation and no timestamps."""
import json
from . import __version__
from .models import Analysis, Evidence, ResolvedFact, Finding
from .policy import load_agp_gradle_policy


def _evidence_dict(item: Evidence) -> dict:
    return {
        "value": item.value,
        "scope": item.scope.value,
        "source": item.source,
        "resolution_path": list(item.resolution_path),
    }


def _fact_dict(fact: ResolvedFact) -> dict:
    return {
        "component": fact.component,
        "value": fact.value,
        "resolution_status": fact.resolution_status.value,
        "evidence": [_evidence_dict(item) for item in fact.evidence],
    }


def _finding_dict(finding: Finding) -> dict:
    return {
        "rule_id": finding.rule_id,
        "status": finding.status.value,
        "message": finding.message,
        "evidence_kind": finding.evidence_kind,
        "policy_source": finding.source_url,
        "required_gradle": finding.required_gradle,
    }


def to_dict(analysis: Analysis) -> dict:
    policy = load_agp_gradle_policy()
    return {
        "schema_version": "0.2",
        "tool_version": __version__,
        "scope": "R02_AGP_GRADLE_MINIMUM_ONLY",
        "status": analysis.status.value,
        "policy_snapshot_date": policy.snapshot_date,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_last_verified": policy.last_verified_date,
        "policy_source": policy.source_url,
        "facts": {
            "agp": _fact_dict(analysis.agp),
            "gradle": _fact_dict(analysis.gradle),
        },
        "findings": [_finding_dict(analysis.finding)],
        "limitations": [
            "This is one AGP/Gradle minimum compatibility check, not overall release readiness.",
            "Local dependency declaration evidence is not proof of the effective Gradle runtime build graph.",
            "No Gradle execution, Android compilation, AAB inspection, native-library inspection, or runtime verification was performed.",
            "Unresolved or conflicting facts produce NOT_EVALUATED, never a failed compatibility conclusion.",
        ],
    }


def to_json(analysis: Analysis) -> str:
    return json.dumps(to_dict(analysis), ensure_ascii=False, sort_keys=True, indent=2)


def to_text(analysis: Analysis) -> str:
    doc = to_dict(analysis)
    lines = [
        "=== RN Readiness / R02 ===",
        f"Scope: {doc['scope']}",
        f"Status: {doc['status'].upper()} (scoped check, not release readiness)",
        "",
        "Facts:",
    ]
    for key in ("agp", "gradle"):
        fact = doc["facts"][key]
        lines.append(
            f"  {key.upper()}: {fact['value'] or 'UNKNOWN'} "
            f"[{fact['resolution_status']}]"
        )
        for item in fact["evidence"]:
            lines.append(
                f"    Evidence: {item['scope']} {item['source']} "
                f"value={item['value'] or 'UNKNOWN'}"
            )
            if item["resolution_path"]:
                lines.append("      Path: " + " -> ".join(item["resolution_path"]))
    finding = doc["findings"][0]
    lines += [
        "",
        "Finding:",
        f"  {finding['rule_id']}: {finding['status'].upper()}",
        "  " + finding["message"],
        "  Evidence: " + finding["evidence_kind"],
        "  Policy: " + (finding["policy_source"] or "N/A"),
        "",
        "NOT VERIFIED: effective Gradle build graph, full Android build, AAB, native libraries, runtime, Play policy.",
    ]
    return "\n".join(lines)
