"""Disabled-X4 differential compatibility, in addition to independent expectations."""

import re

import integrated_checks
from pins import INPUTS, OUTPUTS, CHANNEL_PAYLOADS
from reference import roce_frame


def run(execution, *, width=64):
    label = f"compatibility-w{width}"
    folder = execution.folder / label
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    scenario = integrated_checks.Scenario(width, 17)
    for i in range(32):
        scenario.raw(f"disabled-legacy-{i}",
                     roce_frame(scenario.rng.randbytes(i + 1), version=4 if i & 1 else 6,
                                tags=() if i % 3 == 0 else (0x8100,)), 2)
    source_text = integrated_checks.bench(rel, scenario)
    source_text = source_text.replace("rst_n=1; roce_enable=1;", "rst_n=1; roce_enable=0;")
    source_text = source_text.replace("events!=1", "events!=0")
    parent_outputs = list(OUTPUTS)[:list(OUTPUTS).index("roce_idle")]
    parent_inputs = list(INPUTS)[:list(INPUTS).index("roce_enable")]
    parent_ports = [
        f".{port}({port})" for port in parent_inputs] + [
        f".{port}(parent_{port})" for port in parent_outputs]
    declarations = "\n".join(
        "wire " + ("" if OUTPUTS[port] == "1" else f"[{OUTPUTS[port]}-1:0] ") +
        f"parent_{port};" for port in parent_outputs)
    declarations += "\nparent_furnace_x3_top #(.DATA_WIDTH(W)) parent(" + ",".join(parent_ports) + ");\n"
    payloads = {port for ports in CHANNEL_PAYLOADS.values() for port in ports}
    comparisons = [
        f'if({port} !== parent_{port}) $fatal(1,"DIFFERENTIAL_CONTROL {port}");'
        for port in parent_outputs if port not in payloads]
    comparisons += [
        f'if({valid} && {{{",".join(ports)}}} !== '
        f'{{{",".join("parent_" + port for port in ports)}}}) '
        f'$fatal(1,"DIFFERENTIAL_PAYLOAD {valid}");'
        for valid, ports in CHANNEL_PAYLOADS.items() if valid in parent_outputs]
    comparisons.append(
        'if({wr_valid,rdma_evt_valid,ack_valid,coll_done_valid} !== 0) '
        '$fatal(1,"DISABLED_NEW_OUTPUT");')
    source_text = source_text.replace(
        "input_fire=s_axis_tvalid && s_axis_tready;",
        "\n".join(comparisons) + "\ninput_fire=s_axis_tvalid && s_axis_tready;")
    source_text = source_text.replace("endmodule\n", declarations + "endmodule\n")
    reference_sources = sorted((execution.root / "furnace_x3_reference/rtl").glob("*.sv"))
    names = {path.stem for path in reference_sources}
    pattern = re.compile(r"\b(" + "|".join(sorted(names)) + r")\b")
    copied = folder / "parent"
    copied.mkdir(exist_ok=False)
    for path in reference_sources:
        (copied / path.name).write_text(pattern.sub(lambda m: "parent_" + m.group(0),
                                                  path.read_text()))
    source = folder / "integrated_tb.sv"
    source.write_text(source_text)
    obj = rel / "compatibility-obj"
    sources = [source.relative_to(execution.root).as_posix(),
               *[p.relative_to(execution.root).as_posix()
                 for p in sorted((execution.root / "rtl").glob("*.sv"))],
               *[p.relative_to(execution.root).as_posix() for p in sorted(copied.glob("*.sv"))]]
    code, _, err = execution.run(
        label + "-compile",
        ["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
         "--top-module", "integrated_tb", f"-GW={width}", "--Mdir", obj.as_posix(), *sources])
    if code:
        raise RuntimeError(f"compatibility compile exit {code}: {err[-4000:]}")
    code, out, err = execution.run(
        label + "-behavior",
        [(obj / "Vintegrated_tb").as_posix(), f"+commands={(rel / 'commands.txt').as_posix()}"],
        version_tool="verilator")
    if code or "SUMMARY frames=32 " not in out:
        raise AssertionError(f"compatibility behavior exit {code}: {out[-4000:]} {err[-1000:]}")
    return {"width": width, "independent_and_differential_frames": 32,
            "roce_enable": 0, "measurement": out.strip()}
