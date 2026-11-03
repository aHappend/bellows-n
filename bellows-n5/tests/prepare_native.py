"""Bounded advisory validation of the compiled two-peer verification bridge."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_matrix import matrix
from retention import Run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry", default="tiny64")
    parser.add_argument("--tokens", type=int, default=2)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    run = Run(Path(__file__).resolve().parents[1], "evidence/preparation/verifier-native",
              ["python3", "tests/prepare_native.py", *sys.argv[1:]])
    if args.repair_of:
        run.receipt["repair_of"] = args.repair_of
    error = None
    try:
        run.command(["verilator", "--version"])
        matrix(run, (args.geometry,), (17,), args.tokens)
    except Exception as failure:
        error = failure
    run.finish(error)
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
