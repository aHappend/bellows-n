"""Compact Icarus checks and compiled public arithmetic/tracker comparisons."""

from pathlib import Path
import re
import shutil

from oracle import arithmetic_vectors, bf16_add, bf16_mul, reflected_crc
from prepare_integration import fixtures, top_testbench, write_fixtures
from prepare_reorder import vectors


def icarus(run, name, testbench, rtl, plusargs=()):
    executable = run.output / (name + ".vvp")
    run.command(["iverilog", "-g2012", "-Wall", "-s", testbench,
                 "-o", run.relative(executable), *rtl])
    return run.command(["vvp", run.relative(executable), *plusargs], timeout=600)[1]


def compiled_sv(run, name, top, rtl, parameters=(), plusargs=()):
    directory = run.output / name
    directory.mkdir()
    obj = directory / "compile-obj"
    run.command(["verilator", "--binary", "--timing", "--build", "-j", "4",
                 "-Wno-fatal", "--top-module", top, "--Mdir", run.relative(obj),
                 *parameters, *rtl])
    executable = directory / "simulation"
    shutil.copyfile(obj / ("V" + top), executable)
    executable.chmod(0o755)
    shutil.rmtree(obj)
    return run.command([run.relative(executable), *plusargs])[1]


def arithmetic(run, compact=False, rtl_root=None):
    root = rtl_root or run.root
    if reflected_crc(b"123456789", 32, 0x82f63b78) != 0xe3069283:
        raise AssertionError("independent CRC32C known-answer failure")
    if reflected_crc(b"123456789", 64, 0x9a6c9329ac4bc9b5) != 0xae8b14860a799888:
        raise AssertionError("independent CRC64/NVME known-answer failure")
    vector_path = run.output / "arithmetic.txt"
    count = 0
    with vector_path.open("x") as stream:
        for a, b in arithmetic_vectors(random_count=0 if compact else 20000):
            stream.write(f"{a:04x} {b:04x} {bf16_mul(a,b):04x} {bf16_add(a,b):04x}\n")
            count += 1
            if compact and count >= 1024:
                break
    rtl = ["tests/arithmetic_tb.sv", *[str(p.relative_to(run.root)) for p in
           [root / "rtl" / name for name in
            ("bellows_n5_bf16_mul.sv", "furnace_reduce_alu.sv", "furnace_reduce_lane.sv")]]]
    text = (icarus(run, "arithmetic", "arithmetic_tb", rtl,
                    ["+vectors=" + run.relative(vector_path)]) if compact else
            compiled_sv(run, "arithmetic", "arithmetic_tb", rtl,
                        plusargs=["+vectors=" + run.relative(vector_path)]))
    match = re.search(r"ARITHMETIC compared=(\d+) cycles=(\d+)", text)
    if not match or int(match[1]) != count:
        raise AssertionError("missing exact public arithmetic comparisons")
    run.summary["comparisons"]["arithmetic"] = count


def integration(run, widths=(64, 512), compiled=False, tiny=False):
    for case in ("moe", "write"):
        directory = run.output / ("smoke-" + case)
        directory.mkdir()
        if case == "moe":
            fixtures(directory, **(dict(count=1, k=1, format=0) if tiny else {}))
        else:
            write_fixtures(directory)
        for width in widths:
            testbench = directory / f"top-{width}.sv"
            parameters = (dict(MAX_PACKET_BYTES=1, MAX_SG=1, QPS=1, EXPERTS=1,
                               MAX_K=1, TOKENS=1, MAX_TOKEN_ELEMS=1) if tiny else None)
            testbench.write_text(top_testbench(
                run.root, width, "integration_body.svh" if case == "moe" else "write_body.svh",
                parameters=parameters))
            rtl = [run.relative(testbench)] + [
                run.relative(p) for p in sorted(run.root.glob("rtl/*.sv"))]
            args = ["+fixture=" + run.relative(directory)]
            text = (compiled_sv(run, f"integration-{case}-{width}", "integration_tb",
                                rtl, plusargs=args) if compiled else
                    icarus(run, f"integration-{case}-{width}", "integration_tb", rtl, args))
            label = "INTEGRATION" if case == "moe" else "WRITE"
            if not re.search(label + r" tx_frames=\d+ events=\d+", text):
                raise AssertionError("missing integration comparison counters")
            run.summary["runs"].append(dict(smoke=case, width=width, raw_summary=text.strip()))


def tracker(run, qps_values=(1, 3, 8), seeds=(17, 89, 203), compact=False):
    for qps in qps_values:
        rtl = ["tests/reorder_tb.sv", "rtl/bellows_n5_reorder.sv"]
        if compact:
            executable = run.output / f"reorder-{qps}.vvp"
            run.command(["iverilog", "-g2012", "-Wall", "-s", "reorder_tb",
                         f"-Preorder_tb.QPS={qps}", "-o", run.relative(executable), *rtl])
        else:
            directory = run.output / f"tracker-{qps}"
            directory.mkdir()
            obj = directory / "compile-obj"
            run.command(["verilator", "--binary", "--timing", "--build", "-j", "4",
                         "-Wno-fatal", "--top-module", "reorder_tb",
                         f"-GQPS={qps}", "--Mdir", run.relative(obj), *rtl])
            executable = directory / "simulation"
            shutil.copyfile(obj / "Vreorder_tb", executable)
            executable.chmod(0o755)
            shutil.rmtree(obj)
        for seed in seeds:
            path = run.output / f"tracker-{qps}-{seed}.txt"
            path.write_text(vectors(qps, seed))
            command = (["vvp", run.relative(executable)] if compact
                       else [run.relative(executable)])
            text = run.command([*command, "+vectors=" + run.relative(path)],
                               timeout=600 if compact else 3600)[1]
            match = re.search(r"REORDER requests=(\d+) committed=(\d+) duplicate=(\d+)", text)
            if not match or int(match[2]) < 1024 or int(match[3]) < 256:
                raise AssertionError("missing tracker comparison thresholds")
            run.summary["runs"].append(dict(tracker_qps=qps, seed=seed,
                                           committed=int(match[2]), duplicates=int(match[3])))
