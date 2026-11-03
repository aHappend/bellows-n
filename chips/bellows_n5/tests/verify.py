#!/usr/bin/env python3
"""Portable L1 entry point. Every invocation retains exclusive, source-bound evidence."""

import argparse
from pathlib import Path
import shutil
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_matrix import matrix
from parameters import parameters
from retention import Run, digest, sources
from smoke import arithmetic, combine_leaf, integration, resets, topk, tracker
from synthesis import synthesis


def portable(run):
    directory = run.output / "clean-project"
    directory.mkdir()
    before = {}
    for path in sources(run.root):
        relative = path.relative_to(run.root)
        destination = directory / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        before[str(relative)] = digest(path)
    if {str(p.relative_to(directory)): digest(p) for p in sources(directory)} != before:
        raise AssertionError("copied portable source manifest differs")
    tool_path = run.output / "allowlisted-bin"
    tool_path.mkdir()
    for tool in ("python3", "iverilog", "vvp", "verilator", "yosys", "make",
                 "g++", "gcc", "cc", "c++", "ar", "ld", "as", "sh", "perl",
                 "cat", "echo", "which", "basename", "dirname", "rm", "mkdir",
                 "cp", "sed", "uname", "xargs"):
        resolved = shutil.which(tool)
        if resolved is None:
            raise RuntimeError(f"portable tool is unavailable: {tool}")
        (tool_path / tool).symlink_to(resolved)
    temporary = run.output / "portable-tmp"
    temporary.mkdir()
    home = run.output / "portable-home"
    home.mkdir()
    environment = {"PATH": str(tool_path.resolve()), "LANG": "C", "LC_ALL": "C",
                   "HOME": str(home.resolve()), "TMPDIR": str(temporary.resolve()),
                   "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    run.command(["python3", "tests/verify.py", "--suite", "portable",
                 "--portable-child", "--output-prefix", "evidence/portable-child"],
                cwd=directory, env=environment)
    after = {str(p.relative_to(directory)): digest(p) for p in sources(directory)}
    if after != before:
        raise AssertionError("portable verification altered declared sources")
    run.summary["comparisons"]["portable_manifest_files"] = len(before)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("behavior", "synthesis", "mutations",
                                          "portable", "all"), default="all")
    parser.add_argument("--output-prefix", default="evidence/l1-all")
    parser.add_argument("--portable-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = Run(root, args.output_prefix, ["python3", "tests/verify.py", *sys.argv[1:]])
    error = None
    try:
        if args.portable_child:
            if args.suite != "portable":
                raise ValueError("--portable-child is only valid for portable")
            for command in (["python3", "--version"], ["iverilog", "-V"], ["vvp", "-V"],
                            ["verilator", "--version"]):
                run.command(command)
            arithmetic(run, compact=True)
            combine_leaf(run)
            integration(run, tiny=True)
            resets(run)
            tracker(run, qps_values=(1,), seeds=(17,), compact=True)
            matrix(run, geometries=("tiny64",), seeds=(17,), token_count=2)
            synthesis(run, geometries=("tiny64",), leaves=False)
        else:
            if args.suite in {"behavior", "all"}:
                for command in (["python3", "--version"], ["iverilog", "-V"], ["vvp", "-V"],
                                ["verilator", "--version"]):
                    run.command(command)
                integration(run, tiny=True)
                resets(run)
                topk(run)
                arithmetic(run)
                combine_leaf(run)
                tracker(run, compact=True, qps_values=(1,), seeds=(17,))
                tracker(run)
                parameters(run)
                matrix(run)
            if args.suite in {"synthesis", "all"}:
                synthesis(run)
            if args.suite in {"mutations", "all"}:
                from mutations import mutations
                mutations(run)
            if args.suite in {"portable", "all"}:
                portable(run)
    except Exception as failure:
        error = failure
        (run.output / "failure.txt").write_text(traceback.format_exc())
    run.finish(error)
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
