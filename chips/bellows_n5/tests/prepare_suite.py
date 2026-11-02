"""Targeted, exclusively retained verification-infrastructure diagnostics."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parameters import parameters
from retention import Run
from smoke import arithmetic, integration
from synthesis import synthesis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("smoke", "synthesis", "parameters"))
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    run = Run(Path(__file__).resolve().parents[1],
              "evidence/preparation/verifier-" + args.case,
              ["python3", "tests/prepare_suite.py", *sys.argv[1:]])
    if args.repair_of:
        run.receipt["repair_of"] = args.repair_of
    error = None
    try:
        if args.case == "smoke":
            run.command(["iverilog", "-V"])
            run.command(["vvp", "-V"])
            arithmetic(run, compact=True)
            integration(run, tiny=True)
        elif args.case == "parameters":
            run.command(["iverilog", "-V"])
            run.command(["vvp", "-V"])
            parameters(run)
        else:
            synthesis(run, geometries=("tiny64",), leaves=False)
    except Exception as failure:
        error = failure
    run.finish(error)
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
