"""CLI composition root. Explicit exit codes; scan is read-only."""
import argparse
import sys
from .collector import ProjectInputError, collect_facts
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
    parser = argparse.ArgumentParser(
        description="Nativory — read-only AGP/Gradle minimum compatibility scanner (R02 only)",
    )
    parser.add_argument("first", nargs="?", default=".", help="Repository path, or the scan command")
    parser.add_argument("second", nargs="?", help="Repository path after scan")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    if args.first == "scan":
        path = args.second or "."
    elif args.second is not None:
        parser.error("Expected: nativory or rn-readiness [scan] [PROJECT_PATH]")
    else:
        path = args.first
    try:
        result = run(path)
    except ProjectInputError as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return 4
    except OSError as error:
        print(f"IO ERROR: {error}", file=sys.stderr)
        return 4
    print(to_json(result) if args.json_output else to_text(result))
    return EXIT_CODES[result.status]
