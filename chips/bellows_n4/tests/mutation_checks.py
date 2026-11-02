"""Disposable compiling defects rejected by the unchanged numerical scoreboard."""

import hashlib
import json
import shutil

import alu_checks


FLOAT_MUTATIONS = (
    ("floating-sum-rounding",
     "(normalized6[2] && ((|normalized6[1:0]) || normalized6[3]))",
     "(normalized6[2] && (|normalized6[1:0]))"),
    ("floating-minmax-zero",
     "(a1[31]|b1[31])",
     "(a1[31]&b1[31])"),
)


def run_float(execution):
    control_folder, control_argv = alu_checks.compile_bench(
        execution, 64, label="floating-mutation-control")
    path = control_folder / "vectors.hex"
    coverage = alu_checks.vectors(path, 64, 17)
    vector_argument = f"+vectors={path.relative_to(execution.root).as_posix()}"
    code, out, err = execution.run(
        "floating-mutation-control-behavior", [*control_argv, vector_argument, "+seed=17"],
        version_tool="verilator")
    if code or f"SUMMARY beats={coverage['beats']} compared={coverage['beats']}" not in out:
        raise AssertionError(f"floating mutation unmodified control failed: {out[-3000:]} {err[-1000:]}")
    original = execution.root / "rtl/furnace_reduce_lane.sv"
    text = original.read_text()
    records = []
    for name, before, after in FLOAT_MUTATIONS:
        if text.count(before) != 1:
            raise AssertionError(f"mutation anchor must occur exactly once: {name}")
        changed = text.replace(before, after)
        fingerprint = hashlib.sha256(changed.encode()).hexdigest()
        folder = execution.folder / f"{name}-{fingerprint[:8]}"
        rtl = folder / "rtl"
        rtl.mkdir(parents=True, exist_ok=False)
        shutil.copy2(execution.root / "rtl/furnace_reduce_alu.sv", rtl)
        (rtl / original.name).write_text(changed)
        _, argv = alu_checks.compile_bench(
            execution, 64, rtl_root=rtl.relative_to(execution.root).as_posix(),
            label=name)
        code, out, err = execution.run(
            name + "-behavior", [*argv, vector_argument, "+seed=17"], version_tool="verilator")
        if code == 0 or "NUMERICAL_ASSERTION" not in out + err:
            raise AssertionError(f"{name} not rejected by designated numerical assertion: "
                                 f"exit={code} {out[-3000:]} {err[-1000:]}")
        records.append({"name": name, "target": "rtl/furnace_reduce_lane.sv",
                        "before": before, "after": after,
                        "original_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                        "mutated_sha256": fingerprint, "compile_exit": 0,
                        "behavior_exit": code, "assertion": "NUMERICAL_ASSERTION",
                        "first_failure": (out + err).strip(),
                        "source": (rtl / original.name).relative_to(execution.root).as_posix()})
    (execution.folder / "floating-mutations.json").write_text(json.dumps(records, indent=2) + "\n")
    return {"floating_mutations": records, "control": coverage}
