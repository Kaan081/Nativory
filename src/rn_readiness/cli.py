"""CLI composition root. Explicit exit codes; scan is read-only."""
import argparse
import sys
from .collector import ProjectInputError, collect_facts
from .ndk_collector import trace_ndk
from .ndk_report import to_json as ndk_to_json, to_text as ndk_to_text
from .report import to_json, to_text
from .rules import analyze
from .models import CheckStatus

EXIT_CODES = {
    CheckStatus.CHECKS_PASSED: 0,
    CheckStatus.BLOCKED: 2,
    CheckStatus.UNKNOWN: 3,
}


def run(path: str):
    _, agp, gradle = collect_facts(path)
    return analyze(path, agp, gradle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only AGP/Gradle minimum compatibility spike")
    parser.add_argument(
        "first",
        nargs="?",
        default=".",
        help="Repository path, or a subcommand (scan, trace-ndk)",
    )
    parser.add_argument("second", nargs="?", help="Repository path after subcommand")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    if args.first == "scan":
        path = args.second or "."
        command = "scan"
    elif args.first == "trace-ndk":
        path = args.second or "."
        command = "trace-ndk"
    elif args.second is not None:
        parser.error("Expected: rn-readiness [scan|trace-ndk] [PROJECT_PATH]")
    else:
        path = args.first
        command = "scan"
    try:
        if command == "trace-ndk":
            result = trace_ndk(path)
            print(ndk_to_json(result) if args.json_output else ndk_to_text(result))
            return 0
        result = run(path)
    except ProjectInputError as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return 4
    except OSError as error:
        print(f"IO ERROR: {error}", file=sys.stderr)
        return 4
    print(to_json(result) if args.json_output else to_text(result))
    return EXIT_CODES[result.status]
