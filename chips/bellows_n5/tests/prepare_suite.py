"""Targeted, exclusively retained verification-infrastructure diagnostics."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parameters import parameters
from mutations import MUTATIONS, mutations
from retention import Run
from smoke import arithmetic, combine_leaf, integration, resets
from synthesis import synthesis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("smoke", "synthesis", "parameters", "mutation", "reset"))
    parser.add_argument("--mutation", choices=tuple(MUTATIONS))
    parser.add_argument("--geometry", choices=("tiny64", "default512", "upper"), default="tiny64")
    parser.add_argument("--leaves", action="store_true")
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
            combine_leaf(run)
            integration(run, tiny=True)
        elif args.case == "reset":
            run.command(["iverilog", "-V"])
            run.command(["vvp", "-V"])
            resets(run)
        elif args.case == "parameters":
            run.command(["iverilog", "-V"])
            run.command(["vvp", "-V"])
            parameters(run)
        elif args.case == "mutation":
            if args.mutation is None:
                raise ValueError("a bounded mutation probe requires --mutation")
            mutations(run, names=(args.mutation,))
        else:
            synthesis(run, geometries=(args.geometry,), leaves=args.leaves)
    except Exception as failure:
        error = failure
    run.finish(error)
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
