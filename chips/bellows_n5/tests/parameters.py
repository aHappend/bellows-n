"""Diagnostic-safe illegal parameters and bounded legal single-axis elaborations."""

from native_matrix import GEOMETRIES, PARAMETERS


def parameter_cases():
    base = dict(zip(PARAMETERS, GEOMETRIES["tiny64"]))
    legal = [base, dict(zip(PARAMETERS, GEOMETRIES["tiny512"]))]
    axes = {
        "MAX_PACKET_BYTES": (1, 511, 9216),
        "MAX_SG": (1, 3, 16), "QPS": range(1, 9), "EXPERTS": range(1, 17),
        "MAX_K": range(1, 5), "TOKENS": range(1, 9),
        "MAX_TOKEN_ELEMS": (1, 2, 63, 64, 65, 127, 128, 129, 255, 256),
    }
    for key, values in axes.items():
        for value in values:
            case = {**base, key: value}
            if key == "MAX_K":
                case["EXPERTS"] = value
            legal.append(case)
    illegal = []
    for key, values in {
        "DATA_WIDTH": (0, 128), "MAX_PACKET_BYTES": (0, 9217),
        "MAX_SG": (0, 17), "QPS": (0, 9), "EXPERTS": (0, 17),
        "MAX_K": (0, 5, 2), "TOKENS": (0, 9), "MAX_TOKEN_ELEMS": (0, 257),
    }.items():
        for value in values:
            illegal.append({**base, key: value})
    unique = lambda cases: list({tuple(case.items()): case for case in cases}.values())
    return unique(legal), unique(illegal)


def parameters(run):
    legal, illegal = parameter_cases()
    directory = run.output / "parameters"
    directory.mkdir()
    for expected_legal, cases in ((True, legal), (False, illegal)):
        for index, values in enumerate(cases):
            name = ("legal" if expected_legal else "illegal") + f"-{index}"
            tb, executable = directory / (name + ".sv"), directory / (name + ".vvp")
            tb.write_text(
                "`timescale 1ns/1ps\nmodule parameter_tb;\n"
                "reg clk=0,rst_n=0; always #5 clk=~clk;\n"
                "bellows_n5_top #(" + ",".join(
                    f".{key}({value})" for key, value in values.items()) +
                ") dut(.clk(clk),.rst_n(rst_n));\n"
                "initial begin #11; rst_n=1; #20; $finish; end\nendmodule\n")
            run.command(["iverilog", "-g2012", "-Wall", "-s", "parameter_tb",
                         "-o", run.relative(executable), run.relative(tb),
                         *[run.relative(p) for p in sorted(run.root.glob("rtl/*.sv"))]])
            entry, stdout = run.command(["vvp", run.relative(executable)], timeout=600,
                                        allowed=(0,) if expected_legal else (1,))
            if not expected_legal and "PARAMETER ERROR" not in stdout:
                raise AssertionError(f"missing illegal-parameter diagnostic: {values}")
            run.summary["runs"].append(dict(parameters=values, legal=expected_legal,
                                           tool_exit=entry["exit_code"]))
