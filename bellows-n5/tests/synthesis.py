"""Coarse top-level and mapped-leaf synthesis with whole-netlist inspection."""

import json

from native_matrix import GEOMETRIES, PARAMETERS


def cell_module(document, module_name, instance):
    module = document["modules"][module_name]
    matches = [cell for name, cell in module["cells"].items()
               if name == instance or name.endswith("." + instance)]
    if len(matches) != 1:
        raise AssertionError(f"missing/ambiguous retained instance {module_name}.{instance}")
    cell = matches[0]
    if cell["type"] not in document["modules"]:
        raise AssertionError(f"unresolved module {cell['type']}")
    if not any(isinstance(bit, int) for port in cell["connections"].values() for bit in port):
        raise AssertionError(f"constant disconnected instance {instance}")
    if not document["modules"][cell["type"]]["cells"]:
        raise AssertionError(f"empty retained instance {instance}")
    return cell["type"]


def inspect(document, top, integrated):
    modules = document["modules"]
    counts, memory_bits = {}, 0
    for module in modules.values():
        if module.get("processes"):
            raise AssertionError("unlowered synthesis process")
        for cell in module["cells"].values():
            kind = cell["type"]
            counts[kind] = counts.get(kind, 0) + 1
            if kind in {"$div", "$mod", "$divfloor", "$modfloor"}:
                raise AssertionError(f"forbidden synthesized operator {kind}")
            if kind not in modules and "latch" in kind.lower():
                raise AssertionError(f"inferred latch {kind}")
            if not kind.startswith("$") and kind not in modules:
                raise AssertionError(f"unresolved synthesized module {kind}")
            if kind in {"$mem", "$mem_v2"}:
                memory_bits += (int(cell["parameters"]["WIDTH"], 2) *
                                int(cell["parameters"]["SIZE"], 2))
    if not any("dff" in kind.lower() for kind in counts):
        raise AssertionError("synthesis retained no sequential state")
    if integrated:
        cell_module(document, top, "legacy_core")
        engine = cell_module(document, top, "x5_core")
        for name in ("qp_table", "packet_rx", "packet_tx", "reorder_tracker",
                     "sack_generator", "moe_router"):
            cell_module(document, engine, name)
        router = cell_module(document, engine, "moe_router")
        cell_module(document, router, "topk")
        combiner = cell_module(document, router, "combiner")
        cell_module(document, combiner, "gate_mul")
        cell_module(document, combiner, "gate_sum")
        if memory_bits < 65536 * 8:
            raise AssertionError("missing retained WRITE payload memory")
    return dict(cell_types=counts, memory_bits=memory_bits,
                unresolved_modules=0, latches=0, forbidden_operators=0)


def synthesis(run, geometries=("tiny64", "default512", "upper"), leaves=True):
    run.command(["yosys", "-V"])
    configs = [(name, "bellows_n5_top", GEOMETRIES[name]) for name in geometries]
    if leaves:
        configs.extend([("reorder-mapped", "bellows_n5_reorder", None),
                        ("multiply-mapped", "bellows_n5_bf16_mul", None)])
    for name, top, parameters in configs:
        script, netlist = run.output / (name + ".ys"), run.output / (name + ".json")
        commands = ["read_verilog -sv " + " ".join(
            run.relative(p) for p in sorted(run.root.glob("rtl/*.sv")))]
        if parameters:
            commands.append("hierarchy -check -top " + top + " " + " ".join(
                f"-chparam {key} {value}" for key, value in zip(PARAMETERS, parameters)))
            commands.extend(["proc", "opt_expr", "opt_clean", "check -assert",
                             "fsm", "opt", "wreduce", "memory_dff", "memory_collect",
                             "opt_clean", "check -assert", "stat"])
        else:
            commands.extend([f"synth -top {top}", "check -assert", "stat"])
        commands.append("write_json " + run.relative(netlist))
        script.write_text("\n".join(commands) + "\n")
        run.command(["yosys", "-Q", "-T", "-s", run.relative(script)])
        document = json.loads(netlist.read_text())
        result = inspect(document, top, bool(parameters))
        run.summary["runs"].append(dict(synthesis=name, structural_comparisons=result))
        del document
        run.compress(netlist)
