"""Legacy entry point delegates to the fail-closed corpus runner."""
from __future__ import annotations
import importlib.util, os, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/corpus/NDK_CORPUS_FREEZE_v1.json"
RESULTS = ROOT / "docs/corpus/NDK_CORPUS_RESULTS_v1.json"
CHECKOUT_ROOT = Path(os.environ.get(
    "NDK_CORPUS_ROOT",
    str(Path(tempfile.gettempdir()) / "rn_readiness_ndk_corpus_v1")
))

def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "ndk_guarded",
        ROOT / "scripts/trace_ndk_corpus_only.py"
    )
    if spec is None or spec.loader is None:
        print("HOLD: guarded runner unavailable")
        return 1

    guarded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guarded)

    guarded.ROOT, guarded.CORPUS = ROOT, CORPUS
    guarded.RESULTS, guarded.CHECKOUT_ROOT = (
        RESULTS, CHECKOUT_ROOT
    )
    return guarded.main()

if __name__ == "__main__":
    raise SystemExit(main())
