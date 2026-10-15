"""Versioned, source-linked policy data; this module never scans repositories."""
from importlib.resources import files
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AgpGradlePolicy:
    policy_id: str
    policy_version: int
    last_verified_date: str
    snapshot_date: str
    source_url: str
    minimum_by_series: dict[str, str]


def load_agp_gradle_policy() -> AgpGradlePolicy:
    resource = files("rn_readiness").joinpath("knowledge/agp_gradle_minimums.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    return AgpGradlePolicy(
        policy_id=data["policy_id"],
        policy_version=data["policy_version"],
        last_verified_date=data["last_verified_date"],
        snapshot_date=data["snapshot_date"],
        source_url=data["source_url"],
        minimum_by_series=data["minimum_gradle_by_agp_series"],
    )
