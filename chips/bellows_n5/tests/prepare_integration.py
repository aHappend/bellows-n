"""Retained bounded top-level packet/fragment/weighted-combine experiment."""

import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import combine, ethernet_frame, x5_header


def top_testbench(root, width):
    text = (root / "rtl/bellows_n5_top.sv").read_text()
    header = text.split(") (", 1)[1].split("\n);", 1)[0]
    declarations, connections, initialization = [], [], []
    for line in header.splitlines():
        match = re.fullmatch(r"\s*(input|output) wire\s*(\[[^]]+\])?\s*(.*?)\s*,?\s*", line)
        if not match:
            if line.strip():
                raise ValueError(f"unrecognized top port declaration: {line}")
            continue
        direction, packed, names = match.groups()
        for name in names.rstrip(",").split(","):
            name = name.strip()
            if not name:
                continue
            if not re.fullmatch(r"[a-zA-Z_]\w*", name):
                raise ValueError(f"invalid port identifier {name}")
            declarations.append(f"    {'reg' if direction == 'input' else 'wire'} {packed or ''} {name};")
            connections.append(f".{name}({name})")
            if direction == "input":
                initialization.append(f"        {name}=0;")
    body = (root / "tests/integration_body.svh").read_text()
    return ("\n`timescale 1ns/1ps\nmodule integration_tb;\n"
            f"    localparam DATA_WIDTH={width}, EXPERTS=3, MAX_K=3;\n" +
            "\n".join(declarations) +
            "\n    initial begin\n" + "\n".join(initialization) + "\n    end\n" +
            "    always #5 clk=~clk;\n"
            "    bellows_n5_top #(.DATA_WIDTH(DATA_WIDTH),.MAX_PACKET_BYTES(1),"
            ".MAX_SG(1),.QPS(1),.EXPERTS(3),.MAX_K(3),.TOKENS(3),"
            ".MAX_TOKEN_ELEMS(129)) dut (\n" + ",\n".join(connections) +
            "\n    );\n" + body + "\nendmodule\n")


def fixtures(output):
    weights = [0x3f80, 0x3f00, 0xbf80]
    activation = bytes(i & 255 for i in range(258))
    outputs = [[(0x3e00 + ((j * 17 + e * 31) & 255)) ^ (0x8000 if (j + e) % 5 == 0 else 0)
                for j in range(129)] for e in range(3)]
    expected = []
    for rank in range(3):
        for offset in (0, 256):
            payload = activation[offset:offset + 256]
            header = x5_header(2, destination=2, source=1,
                               psn=len(expected), token=0x12340055,
                               expert=rank, rank=rank, k=3, count=129,
                               offset=offset // 2, payload_bytes=len(payload),
                               format=1, final=offset == 256, weight=weights[rank])
            expected.append(ethernet_frame(header, payload, outgoing=True))
    incoming = []
    received = set()
    base = 0
    for psn in (5, 4, 3, 2, 1, 0):
        rank, fragment = divmod(psn, 2)
        offset = fragment * 256
        payload = b"".join(v.to_bytes(2, "little") for v in outputs[rank])[offset:offset + 256]
        header = x5_header(3, psn=psn, token=0x12340055,
                           expert=rank, rank=rank, k=3, count=129,
                           offset=offset // 2, payload_bytes=len(payload),
                           format=1, final=bool(fragment), weight=weights[rank])
        incoming.append(ethernet_frame(header, payload))
        received.add(psn)
        while base in received:
            received.remove(base)
            base += 1
        bitmap = sum(1 << (value - base) for value in received)
        sack = x5_header(4, destination=2, source=1, psn=psn,
                         payload_bytes=32, sack_base=base)
        expected.append(ethernet_frame(sack, bitmap.to_bytes(32, "little"),
                                       outgoing=True))
    for name, frames in [("stimulus", incoming), ("expected", expected)]:
        # Pad to the declared testbench array; no uninitialized fixture entries.
        data = b"".join(frame + bytes(512 - len(frame)) for frame in frames)
        (output / (name + ".hex")).write_text(
            "\n".join(f"{v:02x}" for v in data + bytes(65536 - len(data))) + "\n")
    for name, frames in [("rx", incoming), ("tx", expected)]:
        (output / (name + "-lengths.hex")).write_text(
            "\n".join(f"{v:08x}" for v in
                      [len(frame) for frame in frames] + [0] * (128 - len(frames))) + "\n")
    combined = b"".join(combine(weights, [outputs[r][j] for r in range(3)]).to_bytes(2, "little")
                        for j in range(129))
    (output / "combined.hex").write_text(
        "\n".join(f"{v:02x}" for v in combined + bytes(1024 - len(combined))) + "\n")


def main():
    root = Path(__file__).resolve().parents[1]
    start = datetime.datetime.now(datetime.timezone.utc)
    output = root / "evidence/preparation" / (
        "verifier-integration-" + start.strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    relative = lambda p: str(p.relative_to(root))
    sources = [p for pattern in ("rtl/*.sv", "tests/*", "design/*.md")
               for p in sorted(root.glob(pattern)) if p.is_file()]
    receipt = {"kind": "verifier-top-integration-preparation",
               "argv": [sys.executable, "tests/prepare_integration.py"],
               "cwd": ".", "start_utc": start.isoformat(), "commands": [],
               "source_sha256": {relative(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sources}}
    for p in sources:
        copy = output / "sources" / p.relative_to(root)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(p.read_bytes())
    exit_code = 1
    try:
        fixtures(output)
        commands = [["iverilog", "-V"], ["vvp", "-V"]]
        for width in (64, 512):
            tb = output / f"top-{width}.sv"
            tb.write_text(top_testbench(root, width))
            executable = output / f"top-{width}.vvp"
            commands.extend([
                ["iverilog", "-g2012", "-Wall", "-s", "integration_tb",
                 "-o", relative(executable), relative(tb)] +
                [relative(p) for p in sorted(root.glob("rtl/*.sv"))],
                ["vvp", relative(executable), "+fixture=" + relative(output)],
            ])
        for index, command in enumerate(commands):
            entry = {"argv": command, "cwd": ".", "timeout_s": 600,
                     "start_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     "stdout": relative(output / f"command-{index}.stdout.txt"),
                     "stderr": relative(output / f"command-{index}.stderr.txt")}
            receipt["commands"].append(entry)
            before = time.monotonic()
            with (root / entry["stdout"]).open("wb") as stdout, (
                    root / entry["stderr"]).open("wb") as stderr:
                try:
                    result = subprocess.run(command, cwd=root, stdout=stdout,
                                            stderr=stderr, timeout=600, check=False)
                    entry.update(exit_code=result.returncode, timed_out=False)
                except subprocess.TimeoutExpired:
                    entry.update(exit_code=None, timed_out=True)
            entry.update(end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         duration_s=time.monotonic() - before)
            if entry["timed_out"] or entry["exit_code"] != 0:
                raise RuntimeError(f"command {index} failed")
        exit_code = 0
    except Exception as error:
        receipt["error"] = str(error)
    finally:
        receipt.update(exit_code=exit_code,
                       end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"receipt": relative(output / "receipt.json"),
                          "exit_code": exit_code}), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
