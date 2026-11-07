"""Reproducible, non-executing app-corpus measurements for Nativory R02.

Never installs dependencies, runs Gradle/Node, or fetches repositories. Checkouts
and any independently verified build facts must be supplied by the operator.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

SHA = re.compile(r"[a-f0-9]{40}\Z")
CASE_ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
VALID_KINDS = {"application", "template"}
TRUTH_METHODS = {"manual_declaration", "gradle_runtime"}


def load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("Unsupported corpus manifest")
    cases = data["cases"]
    if not cases:
        raise ValueError("Manifest has no cases")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Malformed case")
        case_id = case.get("id")
        relative = case.get("scan_root")
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"Invalid scan root for {case_id}")
        # Accept only repository-relative paths, regardless of the host OS.
        # On Windows, Path('/outside').is_absolute() is False, so check both grammars.
        posix_root = PurePosixPath(relative)
        windows_root = PureWindowsPath(relative)
        if (not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id)
                or case_id in seen):
            raise ValueError("Invalid or duplicate case ID")
        seen.add(case_id)
        if (not isinstance(case.get("repository"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", case["repository"])):
            raise ValueError(f"Invalid repository for {case_id}")
        if not isinstance(case.get("commit"), str) or not SHA.fullmatch(case["commit"]):
            raise ValueError(f"Missing exact 40-character SHA for {case_id}")
        if (case.get("kind") not in VALID_KINDS
                or posix_root.is_absolute() or windows_root.anchor
                or ".." in posix_root.parts or ".." in windows_root.parts):
            raise ValueError(f"Invalid scan root or kind for {case_id}")
    return cases


def load_truth(path: Path | None, cases: list[dict]) -> dict:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("facts"), list):
        raise ValueError("Unsupported truth file")
    declared = {case["id"]: case for case in cases}
    facts: dict[str, dict] = {}
    for record in data["facts"]:
        if not isinstance(record, dict):
            raise ValueError("Malformed truth record")
        case_id = record.get("id")
        expected = declared.get(case_id)
        if (expected is None or case_id in facts or record.get("commit") != expected["commit"]
                or record.get("method") not in TRUTH_METHODS
                or not isinstance(record.get("agp"), str)
                or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", record["agp"])
                or not isinstance(record.get("evidence_ref"), str)
                or not record["evidence_ref"].strip()):
            raise ValueError(f"Invalid/unverified truth record: {case_id}")
        facts[case_id] = record
    return facts


def read_head(checkout: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=15,
        )
        sha = result.stdout.strip()
        return sha if SHA.fullmatch(sha) else None
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def tracked_sources_clean(checkout: Path) -> bool:
    """Reject modified tracked files, including staged and unstaged changes."""
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "diff", "--quiet", "HEAD", "--"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def scanner_report(scan_root: Path) -> dict:
    from rn_readiness.cli import run
    from rn_readiness.report import to_dict

    return to_dict(run(str(scan_root)))


def inspect_case(case: dict, checkouts: Path, truth: dict | None = None,
                 *, scan: Callable[[Path], dict] = scanner_report,
                 get_head: Callable[[Path], str | None] = read_head,
                 get_clean: Callable[[Path], bool] = tracked_sources_clean) -> dict:
    """Inspect only a verified pinned checkout; never attempt repair/fetch/install."""
    case_id = case["id"]
    result = {"id": case_id, "kind": case["kind"], "commit": case["commit"],
              "repository": case["repository"], "state": "missing_checkout"}
    checkout = checkouts / case_id
    if not checkout.is_dir():
        return result
    if get_head(checkout) != case["commit"]:
        result["state"] = "revision_mismatch"
        return result
    if not get_clean(checkout):
        result["state"] = "tracked_sources_modified"
        return result
    scan_root = (checkout / case["scan_root"]).resolve()
    if not scan_root.is_relative_to(checkout.resolve()) or not scan_root.is_dir():
        result["state"] = "scan_root_missing"
        return result

    # Presence of a directory is *not* evidence of a complete package-manager install.
    result["node_modules_present"] = (scan_root / "node_modules").is_dir()
    try:
        first = scan(scan_root)
        second = scan(scan_root)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        result["state"] = "scanner_error"
        result["error_type"] = type(error).__name__
        return result
    if first != second:
        result["state"] = "nondeterministic"
        return result
    try:
        agp = first["facts"]["agp"]
        gradle = first["facts"]["gradle"]
        result.update(state="scanned", status=first["status"],
                      agp_value=agp["value"], agp_resolution=agp["resolution_status"],
                      gradle_value=gradle["value"], report=first)
    except (KeyError, TypeError):
        result["state"] = "invalid_report_schema"
        return result
    if truth is not None:
        result["truth"] = {"method": truth["method"], "evidence_ref": truth["evidence_ref"],
                           "agp": truth["agp"]}
        result["agreement"] = ("unresolved" if result["agp_value"] is None
                               else "match" if result["agp_value"] == truth["agp"]
                               else "mismatch")
    return result


def summary(results: list[dict]) -> dict:
    scans = [r for r in results if r["state"] == "scanned"]
    apps = [r for r in scans if r["kind"] == "application"]
    matched = [r for r in scans if r.get("agreement") == "match"]
    mismatches = [r for r in scans if r.get("agreement") == "mismatch"]
    return {
        "selected": len(results),
        "scanned": len(scans),
        "incomplete": len(results) - len(scans),
        "applications_scanned": len(apps),
        "applications_with_node_modules_dir": sum(r["node_modules_present"] for r in apps),
        "applications_agp_resolved": sum(r["agp_resolution"] == "resolved" for r in apps),
        "truth_matches": len(matched),
        "manual_declaration_matches": sum(r["truth"]["method"] == "manual_declaration" for r in matched),
        "gradle_runtime_matches": sum(r["truth"]["method"] == "gradle_runtime" for r in matched),
        "manual_declaration_mismatches": sum(r["truth"]["method"] == "manual_declaration" for r in mismatches),
        "gradle_runtime_mismatches": sum(r["truth"]["method"] == "gradle_runtime" for r in mismatches),
        "build_successes": "NOT_MEASURED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="docs/corpus/R02_APP_CORPUS_V2.json")
    parser.add_argument("--checkouts", help="Parent directory containing <case-id>/ pinned Git checkouts")
    parser.add_argument("--truth", help="Optional independently verified ground-truth JSON")
    parser.add_argument("--output", help="Write deterministic result JSON outside scanned checkout trees")
    parser.add_argument("--plan", action="store_true", help="List frozen cases, without scanning")
    args = parser.parse_args(argv)
    try:
        cases = load_manifest(Path(args.manifest))
        truths = load_truth(Path(args.truth) if args.truth else None, cases)
    except (ValueError, OSError, json.JSONDecodeError) as err:
        print(f"MANIFEST ERROR: {err}", file=sys.stderr)
        return 4
    if args.plan:
        for case in cases:
            print(f"{case['id']:22} {case['kind']:12} {case['repository']} @ {case['commit']}")
        return 0
    if not args.checkouts or not args.output:
        parser.error("Scanning requires --checkouts and --output")
    checkouts = Path(args.checkouts).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if output.is_relative_to(checkouts):
        print("ERROR: output must be outside the checkout directory", file=sys.stderr)
        return 4
    results = [inspect_case(case, checkouts, truths.get(case["id"])) for case in cases]
    body = {"schema_version": 1, "source": "R02_APP_CORPUS_V2",
            "summary": summary(results), "cases": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    s = body["summary"]
    print(f"Scanned: {s['scanned']}/{s['selected']} | app AGP resolved: "
          f"{s['applications_agp_resolved']}/{s['applications_scanned']} | "
          f"runtime truth matches: {s['gradle_runtime_matches']} | "
          f"incomplete: {s['incomplete']}")
    print(f"Report: {output}")
    if s["incomplete"] or s["gradle_runtime_mismatches"] or s["manual_declaration_mismatches"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
