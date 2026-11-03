"""Compiling disposable defects must cause independently observed output mismatches."""

import json
import shutil

from native_matrix import (build, packet_stimulus, stimulus, validate, validate_packets)
from smoke import arithmetic, integration


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise AssertionError(f"mutation anchor is not unique: {old}")
    return text.replace(old, new, 1)


def arrival_order(text):
    text = replace_once(text, "reg [2*MAX_K-1:0] returned [0:TOKENS-1];", """
    reg [2*MAX_K-1:0] returned [0:TOKENS-1];
    reg [2*MAX_K-1:0] mutation_arrival [0:TOKENS-1];
    reg [2:0] mutation_count [0:TOKENS-1];
    reg [16*MAX_K-1:0] mutation_weights;
    integer mutation_i;
    always @* begin
        mutation_weights=0;
        for (mutation_i=0;mutation_i<MAX_K;mutation_i=mutation_i+1)
            mutation_weights[16*mutation_i +:16]=
                weights[cslot][16*mutation_arrival[cslot][2*mutation_i +:2] +:16];
    end
    wire [1:0] mutation_rank=mutation_arrival[cslot][2*comb_rank +:2];
""")
    text = replace_once(text, ".cmd_weights(weights[cslot])", ".cmd_weights(mutation_weights)")
    text = replace_once(text, "((cslot*MAX_K+comb_rank)<<9)",
                        "((cslot*MAX_K+mutation_rank)<<9)")
    text = replace_once(text, "completion_status[n]<=0;", """
                    completion_status[n]<=0;
                    mutation_count[n]<=0; mutation_arrival[n]<=0;""")
    text = replace_once(text, "formats[free_slot]<=x5_moe_cmd_format;", """
                    mutation_count[free_slot]<=0; mutation_arrival[free_slot]<=0;
                    formats[free_slot]<=x5_moe_cmd_format;""")
    text = replace_once(text,
                        "else returned[rx_slot_hold][2*rx_rank_hold+rx_frag_hold]<=1;", """
                        else begin
                            returned[rx_slot_hold][2*rx_rank_hold+rx_frag_hold]<=1;
                            if (!formats[rx_slot_hold] || elems[rx_slot_hold]<=128 ||
                                returned[rx_slot_hold][2*rx_rank_hold+(rx_frag_hold ^ 1'b1)]) begin
                                mutation_arrival[rx_slot_hold]
                                    [2*mutation_count[rx_slot_hold] +:2]<=rx_rank_hold;
                                mutation_count[rx_slot_hold]<=mutation_count[rx_slot_hold]+1'b1;
                            end
                        end""")
    return text


MUTATIONS = {
    "accept-d256": ("bellows_n5_reorder.sv",
                   lambda s: replace_once(s, "delta>=24'd256", "delta>24'd256"), "tiny64"),
    "duplicate-side-effect": ("bellows_n5_reorder.sv",
                             lambda s: s.replace("classification<=1;", "classification<=0;"),
                             "tiny64"),
    "sack-bit-rotation": ("bellows_n5_reorder.sv",
                         lambda s: replace_once(s, "snapshot_base[7:0]+cursor",
                                                "snapshot_base[7:0]+cursor+8'd1"), "tiny64"),
    "topk-reversed-tie": ("bellows_n5_topk.sv",
                         lambda s: replace_once(s, "candidate>best_score",
                                                "candidate>=best_score"), "odd"),
    "bf16-byte-stride": ("bellows_n5_moe_router.sv",
                        lambda s: replace_once(s,
                            "(formats[cslot] ? ({8'b0,comb_elem}<<1) : {8'b0,comb_elem})",
                            "{8'b0,comb_elem}"), "odd"),
    "expert-arrival-order": ("bellows_n5_moe_router.sv", arrival_order, "odd"),
    "bf16-halfway-truncation": ("bellows_n5_bf16_mul.sv",
                               lambda s: replace_once(s,
                                   "(guard5 && (sticky5 || retained5[0]))",
                                   "(guard5 && sticky5)"), None),
    "legacy-crc-polynomial": ("furnace_crc_beat_pipeline.sv",
                             lambda s: replace_once(s, "32'h82f63b78", "32'h82f63b79"), None),
}


def native_case(run, executable, name, geometry):
    directory = run.output / name
    directory.mkdir()
    tokens = stimulus(directory, geometry, 17, 8)
    records = packet_stimulus(directory, geometry, 17, compact=True)
    entry, _ = run.command([run.relative(executable), run.relative(directory), "17"],
                           allowed=(0, 1))
    return directory, tokens, records, entry


def mutations(run, names=None):
    selected = {name: MUTATIONS[name] for name in (names or MUTATIONS)}
    run.command(["verilator", "--version"])
    controls = {}
    for geometry in sorted({record[2] for record in selected.values() if record[2]}):
        controls[geometry] = build(run, geometry, label="control-" + geometry)
        directory, tokens, records, entry = native_case(
            run, controls[geometry], "control-" + geometry, geometry)
        if entry["exit_code"] != 0:
            raise AssertionError("original native sensitivity control failed")
        validate_packets(directory, records, thresholds=False)
        validate(directory, geometry, tokens, 8)
    if any(record[2] is None for record in selected.values()):
        control_root = run.output / "arithmetic-control"
        control_root.mkdir()
        saved = run.output
        try:
            run.output = control_root
            if "bf16-halfway-truncation" in selected:
                arithmetic(run)
            if "legacy-crc-polynomial" in selected:
                integration(run, widths=(64,), compiled=True, cases=("write",))
        finally:
            run.output = saved
    for name, (filename, transform, geometry) in selected.items():
        copy = run.output / "mutants" / name
        (copy / "rtl").mkdir(parents=True)
        for source in sorted(run.root.glob("rtl/*.sv")):
            shutil.copyfile(source, copy / "rtl" / source.name)
        source = copy / "rtl" / filename
        original = source.read_text()
        mutated = transform(original)
        if mutated == original:
            raise AssertionError(f"mutation made no source change: {name}")
        source.write_text(mutated)
        observed = None
        if geometry:
            executable = build(run, geometry, rtl_root=copy, label=name)
            directory, tokens, records, entry = native_case(run, executable, name, geometry)
            try:
                validate_packets(directory, records, thresholds=False)
                validate(directory, geometry, tokens, 8)
            except AssertionError as mismatch:
                observed = str(mismatch)
                if "missing" in observed or "unknown trace" in observed:
                    raise AssertionError(f"{name} did not yield an actual compared mismatch: {mismatch}")
        else:
            directory = run.output / name
            directory.mkdir()
            saved = run.output
            first_command = len(run.receipt["commands"])
            try:
                run.output = directory
                if name == "bf16-halfway-truncation":
                    arithmetic(run, rtl_root=copy)
                else:
                    integration(run, widths=(64,), compiled=True, rtl_root=copy,
                                cases=("write",))
            except RuntimeError:
                entries = run.receipt["commands"][first_command:]
                if not entries or any(e["timed_out"] for e in entries):
                    raise
                last = entries[-1]
                if last["exit_code"] == 0 or "simulation" not in last["argv"][0]:
                    raise AssertionError(f"{name}: tool/compiler failure is not sensitivity")
                stdout = (run.root / last["stdout"]).read_text()
                expected_label = "MUL mismatch" if name == "bf16-halfway-truncation" else "legacy CRC mismatch"
                if expected_label not in stdout:
                    raise AssertionError(f"{name}: no public-output comparison failure")
                observed = next(line for line in stdout.splitlines() if expected_label in line)
            finally:
                run.output = saved
        if observed is None:
            raise AssertionError(f"undetected compiling mutation: {name}")
        run.summary["runs"].append(dict(mutation=name, observed_public_mismatch=observed))
    if sum("mutation" in result for result in run.summary["runs"]) != len(selected):
        raise AssertionError("missing required mutation rejection")
