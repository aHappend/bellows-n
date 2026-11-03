"""Real parameter elaboration, explicit rejection and retained-memory synthesis."""

import json


CONFIGURATIONS = [(w, packet, scatter, qps)
                  for w in (64, 512)
                  for packet, scatter, qps in ((9216, 16, 8), (1, 1, 1),
                                               (128, 1, 1), (257, 3, 3))]
ILLEGAL = [(name, value)
           for name, values in (("DATA_WIDTH", (0, 32)),
                                ("MAX_PACKET_BYTES", (0, 9217)),
                                ("MAX_SG", (0, 17)), ("QPS", (0, 9)))
           for value in values]


def run(execution, *, compact=False):
    folder = execution.folder / "structural"
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    rtl = [p.relative_to(execution.root).as_posix()
           for p in sorted((execution.root / "rtl").glob("*.sv"))]
    compared = []
    for name, value in ILLEGAL:
        label = f"illegal-{name}-{value}"
        source = folder / f"{label}.sv"
        source.write_text(
            "`timescale 1ns/1ps\nmodule parameter_tb;\n"
            f"bellows_n4_top #(.{name}({value})) dut();\n"
            'initial begin #10; $fatal(1,"ILLEGAL_PARAMETER_ACCEPTED"); end\nendmodule\n')
        binary = rel / f"{label}.vvp"
        code, _, err = execution.run(
            label + "-compile",
            ["iverilog", "-g2012", "-Wall", "-s", "parameter_tb", "-o",
             binary.as_posix(), source.relative_to(execution.root).as_posix(), *rtl])
        if code:
            raise AssertionError(f"{label} did not reach its explicit diagnostic: {err[-3000:]}")
        code, out, err = execution.run(label + "-diagnostic", ["vvp", binary.as_posix()])
        if code == 0 or "PARAMETER ERROR:" not in out + err or "ILLEGAL_PARAMETER_ACCEPTED" in out + err:
            raise AssertionError(f"{label} explicit rejection missing: {out} {err}")
        compared.append({"parameter": name, "value": value, "diagnostic_exit": code})
    synthesis = []
    configs = [(64, 128, 1, 1)] if compact else CONFIGURATIONS
    for width, packet, scatter, qps in configs:
        label = f"synthesis-w{width}-p{packet}-sg{scatter}-q{qps}"
        script = folder / f"{label}.ys"
        netlist = folder / f"{label}.json"
        script.write_text(
            "read_verilog -sv " + " ".join(rtl) + "\n"
            f"chparam -set DATA_WIDTH {width} -set MAX_PACKET_BYTES {packet} "
            f"-set MAX_SG {scatter} -set QPS {qps} bellows_n4_top\n"
            "hierarchy -check -top bellows_n4_top\n"
            "proc\nopt_expr\nopt_clean\ncheck -noinit -assert\n"
            "memory -nomap\nopt_clean\ncheck -noinit -assert\n"
            "stat\nwrite_json " + netlist.relative_to(execution.root).as_posix() + "\n")
        code, out, err = execution.run(
            label, ["yosys", "-Q", "-T", "-s", script.relative_to(execution.root).as_posix()])
        if code:
            raise RuntimeError(f"{label} Yosys exit {code}: {out[-3000:]} {err[-2000:]}")
        modules = json.loads(netlist.read_text())["modules"]
        counts = {}
        for module in modules.values():
            if module.get("attributes", {}).get("blackbox") in (1, "00000000000000000000000000000001"):
                raise AssertionError(f"{label} black-box implementation")
            for cell in module.get("cells", {}).values():
                kind = cell["type"]
                counts[kind] = counts.get(kind, 0) + 1
                if "latch" in kind.lower() or kind in ("$div", "$mod", "$divfloor", "$modfloor"):
                    raise AssertionError(f"{label} forbidden synthesized cell {kind}")
                if not kind.startswith("$") and kind not in modules:
                    raise AssertionError(f"{label} undefined implementation {kind}")
        required = {
            "bellows_n4_top": ("legacy_core", "roce_rx"),
            "furnace_roce_rx": ("parser", "psn_tracker", "dmp_engine", "collective_engine"),
            "furnace_collective_engine": ("reduce_alu",),
        }
        for name, instances in required.items():
            candidates = [m for m in modules.values()
                          if m.get("attributes", {}).get("hdlname", "").lstrip("\\").split()[-1:] == [name]]
            if name in modules:
                candidates.append(modules[name])
            if not candidates:
                raise AssertionError(f"{label} missing substantive module {name}")
            for instance in instances:
                if not any(any(cell_name.split(".")[-1] == instance
                               for cell_name in module.get("cells", {}))
                           for module in candidates):
                    raise AssertionError(f"{label} missing hierarchy {name}.{instance}")
        top = modules["bellows_n4_top"]
        for port in ("wr_valid", "wr_data", "wr_addr", "rdma_evt_valid", "ack_data", "coll_done_valid"):
            if all(isinstance(bit, str) for bit in top["ports"][port]["bits"]):
                raise AssertionError(f"{label} constant active output {port}")
        state_cells = sum(n for kind, n in counts.items()
                          if "dff" in kind.lower() or kind.startswith("$mem"))
        if state_cells < 16:
            raise AssertionError(f"{label} trivial connectivity/state count {state_cells}")
        synthesis.append({"width": width, "max_packet_bytes": packet, "max_sg": scatter,
                          "qps": qps, "state_cells": state_cells, "latches": 0,
                          "division_remainder_cells": 0,
                          "netlist": netlist.relative_to(execution.root).as_posix(),
                          "cell_types": counts})
    return {"illegal_parameters": compared, "synthesis": synthesis}
