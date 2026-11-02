"""Portable FURNACE-X4 verification entrypoint; independent Verifier ownership."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution import Execution, fresh
import alu_checks
import integrated_checks
import legacy_leaf_checks
import mutation_checks
import parser_checks
import qos_checks
import structural_checks
from reference import self_check


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--probe", choices=("parser", "alu", "alu-matrix", "integrated", "protocol",
                                             "structural", "stale-address", "stale-address-icarus",
                                             "floating-mutations", "legacy-leaves", "legacy-mutations",
                                             "qos", "packet-mutations", "boundaries"),
                           help="bounded preparation diagnostic")
    arguments.add_argument("--repair-of", action="append", default=[],
                           help="project-relative retained failure receipt")
    options = arguments.parse_args()
    folder = fresh(f"{options.probe}-reference" if options.probe else "l1",
                   preparation=bool(options.probe))
    execution = Execution(folder)
    try:
        self_check()
        if options.probe == "parser":
            coverage = parser_checks.run(execution)
        elif options.probe == "alu":
            coverage = alu_checks.run(execution, widths=(64,), seeds=(17,))
        elif options.probe == "alu-matrix":
            coverage = alu_checks.run(execution)
        elif options.probe == "integrated":
            coverage = {"integrated": integrated_checks.run(execution, compact=True)}
        elif options.probe == "protocol":
            coverage = {"integrated": integrated_checks.run(execution)}
        elif options.probe == "structural":
            coverage = structural_checks.run(execution, compact=True)
        elif options.probe == "stale-address":
            coverage = {"integrated": integrated_checks.run(execution, stale_address=True)}
        elif options.probe == "stale-address-icarus":
            coverage = {"integrated": integrated_checks.run(
                execution, stale_address=True, simulator="iverilog")}
        elif options.probe == "floating-mutations":
            coverage = mutation_checks.run_float(execution)
        elif options.probe == "legacy-leaves":
            coverage = legacy_leaf_checks.run(execution)
        elif options.probe == "legacy-mutations":
            coverage = mutation_checks.run_legacy(execution)
        elif options.probe == "qos":
            coverage = qos_checks.run(execution)
        elif options.probe == "packet-mutations":
            coverage = mutation_checks.run_packet(execution)
        elif options.probe == "boundaries":
            coverage = {"boundaries": [
                integrated_checks.run(execution, width=width, boundary=geometry,
                                      prefix=f"boundary-p{geometry[0]}")
                for width in (64, 512)
                for geometry in ((1, 1, 1), (128, 1, 1), (257, 3, 3))]}
        else:
            coverage = parser_checks.run(execution)
            coverage.update(alu_checks.run(execution, widths=(64,), seeds=(17,),
                                           simulator="iverilog", compact=True))
            coverage["alu_full"] = alu_checks.run(execution)
            coverage["integrated"] = [
                integrated_checks.run(execution, width=width, seed=seed)
                for width in (64, 512) for seed in (17, 89, 203)]
            coverage["boundaries"] = [
                integrated_checks.run(execution, width=width, boundary=geometry,
                                      prefix=f"boundary-p{geometry[0]}")
                for width in (64, 512)
                for geometry in ((1, 1, 1), (128, 1, 1), (257, 3, 3))]
            coverage.update(structural_checks.run(execution))
            coverage.update(mutation_checks.run_float(execution))
            coverage["legacy_leaves"] = legacy_leaf_checks.run(execution)
            coverage["legacy_mutations"] = mutation_checks.run_legacy(execution)
            coverage["qos"] = qos_checks.run(execution)
            coverage.update(mutation_checks.run_packet(execution))
    except (AssertionError, RuntimeError, FileNotFoundError) as error:
        receipt = execution.finish("failed", str(error), repair_of=options.repair_of)
        print(f"FAILED {error}\nReceipt: {receipt}", flush=True)
        return 1
    receipt = execution.finish("passed", "independent reference comparisons",
                               repair_of=options.repair_of, **coverage)
    print(f"PASSED executed reference comparisons; receipt: {receipt}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
