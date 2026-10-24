"""Presentation for NDK provenance trace; no compatibility conclusions."""
import json

from . import __version__
from .ndk_models import NdkDeclaration, NdkTraceResult


def _declaration_dict(item: NdkDeclaration) -> dict:
    return {
        "owner": item.owner,
        "owner_type": item.owner_type.value,
        "source": item.source,
        "value": item.value,
        "resolution_kind": item.resolution_kind.value,
        "resolution_path": list(item.resolution_path),
    }


def to_dict(result: NdkTraceResult) -> dict:
    return {
        "schema_version": "0.1-ndk-provenance",
        "tool_version": __version__,
        "scope": "NDK_PROVENANCE_TRACE",
        "declarations": [_declaration_dict(item) for item in result.declarations],
        "attention_signals": list(result.attention_signals),
        "limitations": [
            "This command traces NDK declaration provenance only; it does not evaluate NDK compatibility.",
            "Different literal NDK pins across project and dependencies are observed declaration "
            "differences only; they are not proof of effective Gradle build selection or participation.",
            "Attention signals exclude common example/sample/demo/test paths inside dependency trees.",
            "root_inherited and unsupported_expression entries do not claim an effective NDK version.",
            "No Gradle execution, Node resolution, network access, or build graph evaluation was performed.",
        ],
    }


def to_json(result: NdkTraceResult) -> str:
    return json.dumps(to_dict(result), ensure_ascii=False, sort_keys=True, indent=2)


def to_text(result: NdkTraceResult) -> str:
    doc = to_dict(result)
    lines = [
        "=== RN Readiness / NDK Provenance Trace ===",
        f"Scope: {doc['scope']}",
        "",
        "Declarations:",
    ]
    if not doc["declarations"]:
        lines.append("  (none)")
    for item in doc["declarations"]:
        value = item["value"] or "—"
        lines.append(
            f"  [{item['owner_type']}] {item['owner']} "
            f"{item['resolution_kind']} value={value}"
        )
        lines.append(f"    Source: {item['source']}")
        if item["resolution_path"]:
            lines.append("    Path: " + " -> ".join(item["resolution_path"]))
    if doc["attention_signals"]:
        lines += ["", "Attention signals:"]
        for signal in doc["attention_signals"]:
            lines.append(f"  - {signal}")
    lines += [
        "",
        "NOT VERIFIED: effective Gradle NDK resolution, native build graph, or runtime compatibility.",
    ]
    return "\n".join(lines)
