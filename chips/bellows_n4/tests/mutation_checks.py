"""Disposable compiling defects rejected by the unchanged numerical scoreboard."""

import hashlib
import json
import shutil

import alu_checks
import legacy_leaf_checks
import integrated_checks
import qos_checks


FLOAT_MUTATIONS = (
    ("floating-sum-rounding",
     "(normalized6[2] && ((|normalized6[1:0]) || normalized6[3]))",
     "(normalized6[2] && (|normalized6[1:0]))"),
    ("floating-minmax-zero",
     "(a1[31]|b1[31])",
     "(a1[31]&b1[31])"),
)

LEGACY_MUTATIONS = (
    ("rss-bit-order", "furnace_rss_toeplitz.sv",
     "in_tuple[295]) ? in_key[327:296]", "in_tuple[294]) ? in_key[327:296]",
     "RSS_ASSERTION"),
    ("tcam-priority", "furnace_classifier64.sv",
     "wire current_wins = !found && enable_q && equal_q;",
     "wire current_wins = enable_q && equal_q;", "TCAM_ASSERTION"),
)

PACKET_MUTATIONS = (
    ("legacy-crc32c", "furnace_crc_packet_accumulator.sv",
     "32'h82f63b78", "32'h82f63b79", "CRC_ASSERTION"),
    ("legacy-crc64-nvme", "furnace_crc_packet_accumulator.sv",
     "64'h9a6c9329ac4bc9b5", "64'h9a6c9329ac4bc9b4", "CRC_ASSERTION"),
    ("psn-advance", "furnace_psn_tracker.sv",
     "expected[result_index]<=expected[result_index]+24'd1;",
     "expected[result_index]<=expected[result_index]+24'd2;", "ACK_ASSERTION"),
    ("dmp-protection", "furnace_psn_tracker.sv",
     "result_address<base[cursor]", "1'b0", "DMP_ADDRESS_ASSERTION"),
    ("payload-offset", "furnace_roce_rx.sv",
     "replay_pointer<=parser_payload_start;",
     "replay_pointer<=parser_payload_start+14'd1;", "TENSOR_ASSERTION"),
    ("drr-accounting", "furnace_drr_scheduler.sv",
     "deficit[evt_queue]<=deficit[evt_queue]-evt_bytes;",
     "deficit[evt_queue]<=deficit[evt_queue];", "DRR_ASSERTION"),
)


def run_packet(execution):
    control = integrated_checks.run(execution, compact=True, prefix="packet-mutation-control")
    qos_control = qos_checks.run(execution, prefix="qos-mutation-control")
    records = []
    for name, filename, before, after, assertion in PACKET_MUTATIONS:
        original = execution.root / "rtl" / filename
        text = original.read_text()
        if text.count(before) != 1:
            raise AssertionError(f"mutation anchor must occur exactly once: {name}")
        changed = text.replace(before, after)
        fingerprint = hashlib.sha256(changed.encode()).hexdigest()
        folder = execution.folder / f"{name}-{fingerprint[:8]}"
        rtl = folder / "rtl"
        rtl.mkdir(parents=True, exist_ok=False)
        for source in sorted((execution.root / "rtl").glob("*.sv")):
            shutil.copy2(source, rtl)
        (rtl / filename).write_text(changed)
        detected = None
        try:
            if name == "drr-accounting":
                qos_checks.run(execution, rtl_root=rtl.relative_to(execution.root).as_posix(),
                               prefix=name)
            else:
                integrated_checks.run(
                    execution, compact=True, rtl_root=rtl.relative_to(execution.root).as_posix(),
                    prefix=name)
        except AssertionError as error:
            if assertion not in str(error):
                raise
            detected = str(error)
        if detected is None:
            raise AssertionError(f"{name} survived its designated protocol/numerical assertion")
        records.append({"name": name, "target": f"rtl/{filename}",
                        "before": before, "after": after,
                        "original_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                        "mutated_sha256": fingerprint, "compile_exit": 0,
                        "assertion": assertion, "first_failure": detected,
                        "source": (rtl / filename).relative_to(execution.root).as_posix()})
    (execution.folder / "packet-mutations.json").write_text(json.dumps(records, indent=2) + "\n")
    return {"packet_mutations": records, "control": control, "qos_control": qos_control}


def run_legacy(execution):
    control = legacy_leaf_checks.run(execution, prefix="legacy-mutation-control")
    records = []
    for name, filename, before, after, assertion in LEGACY_MUTATIONS:
        original = execution.root / "rtl" / filename
        text = original.read_text()
        if text.count(before) != 1:
            raise AssertionError(f"mutation anchor must occur exactly once: {name}")
        changed = text.replace(before, after)
        fingerprint = hashlib.sha256(changed.encode()).hexdigest()
        folder = execution.folder / f"{name}-{fingerprint[:8]}"
        rtl = folder / "rtl"
        rtl.mkdir(parents=True, exist_ok=False)
        for target in ("furnace_rss_toeplitz.sv", "furnace_classifier64.sv"):
            shutil.copy2(execution.root / "rtl" / target, rtl)
        (rtl / filename).write_text(changed)
        detected = None
        try:
            legacy_leaf_checks.run(
                execution, rtl_root=rtl.relative_to(execution.root).as_posix(), prefix=name)
        except AssertionError as error:
            if assertion not in str(error):
                raise
            detected = str(error)
        if detected is None:
            raise AssertionError(f"{name} survived the designated protocol/numerical assertion")
        records.append({"name": name, "target": f"rtl/{filename}",
                        "before": before, "after": after,
                        "original_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                        "mutated_sha256": fingerprint, "assertion": assertion,
                        "first_failure": detected,
                        "source": (rtl / filename).relative_to(execution.root).as_posix()})
    (execution.folder / "legacy-mutations.json").write_text(json.dumps(records, indent=2) + "\n")
    return {"legacy_mutations": records, "control": control}


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
