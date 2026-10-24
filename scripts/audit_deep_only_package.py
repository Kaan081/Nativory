"""Compare deep-only Gradle layout discovery across commits."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from rn_readiness.ndk_collector import trace_ndk


def make_fixture() -> Path:
    tmp = Path(tempfile.mkdtemp())
    repo = tmp / "app"
    pkg = repo / "node_modules" / "deep-native-package"
    gradle = pkg / "native" / "android" / "module" / "build.gradle"
    gradle.parent.mkdir(parents=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "deep-native-package"}),
        encoding="utf-8",
    )
    gradle.write_text('ndkVersion "26.0.1"\n', encoding="utf-8")
    (repo / "android").mkdir()
    (repo / "android" / "build.gradle").write_text("// project stub\n", encoding="utf-8")
    return repo


def main() -> int:
    repo = make_fixture()
    try:
        result = trace_ndk(str(repo))
        hits = [
            (d.owner, d.source, d.value, d.resolution_kind.value)
            for d in result.declarations
            if d.owner == "deep-native-package"
        ]
        print("hits=", hits)
        return 0 if hits else 1
    finally:
        shutil.rmtree(repo.parent)


if __name__ == "__main__":
    raise SystemExit(main())
