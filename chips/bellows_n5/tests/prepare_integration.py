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


def top_testbench(root, width, body_name="integration_body.svh", parameters=None):
    parameters = parameters or dict(MAX_PACKET_BYTES=128, MAX_SG=1, QPS=1,
                                    EXPERTS=3, MAX_K=3, TOKENS=3, MAX_TOKEN_ELEMS=129)
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
    body = (root / "tests" / body_name).read_text()
    reset_checks = "\n".join(
        f"        if ({name} !== 0) $fatal(1,\"reset output {name}\");"
        for name in re.findall(r"\.(x5_\w+)\(", ",".join(connections))
        if any(declaration.endswith(" " + name + ";") and "wire " in declaration
               for declaration in declarations))
    return ("\n`timescale 1ns/1ps\nmodule integration_tb;\n"
            f"    localparam DATA_WIDTH={width};\n" +
            "\n".join(f"    localparam {name}={value};"
                      for name, value in parameters.items()) + "\n" +
            "\n".join(declarations) +
            "\n    initial begin\n" + "\n".join(initialization) + "\n    end\n" +
            "    always #5 clk=~clk;\n"
            "    bellows_n5_top #(.DATA_WIDTH(DATA_WIDTH)," +
            ",".join(f".{name}({name})" for name in parameters) +
            ") dut (\n" + ",\n".join(connections) +
            "\n    );\n"
            "    always @(posedge clk or negedge clk) if (!rst_n) begin\n" +
            reset_checks + "\n    end\n" + body + "\nendmodule\n")


def write_fixtures(output):
    payload = bytes(((i * 7) ^ 0x5a) & 255 for i in range(513))
    expected = []
    for offset in (0, 256, 512):
        fragment = payload[offset:offset + 256]
        header = x5_header(1, destination=2, source=1, psn=len(expected),
                           token=0xabcd0123, count=513, offset=offset,
                           payload_bytes=len(fragment), final=offset == 512,
                           address=0x1800, rkey=0x01020304)
        expected.append(ethernet_frame(header, fragment, outgoing=True))
    incoming, events, mem_data, mem_addresses = [], [], bytearray(), []

    def event(status, kind=0, token=0, psn=0):
        return (status << 67) | (kind << 59) | (token << 24) | psn

    for psn, offset, base, bitmap in [(1, 256, 0, 2), (0, 0, 2, 0), (2, 512, 3, 0),
                                     (1, 256, 3, 0), (259, 0, 3, 0)]:
        fragment = payload[offset:offset + 256]
        header = x5_header(1, psn=psn, token=0xabcd0123, count=513, offset=offset,
                           payload_bytes=len(fragment), final=offset == 512,
                           address=0x2000, rkey=0x01020304)
        incoming.append(ethernet_frame(header, fragment))
        status = 0 if len(incoming) <= 3 else (1 if len(incoming) == 4 else 2)
        events.append(event(status, 1, 0xabcd0123, psn))
        sack = x5_header(4, destination=2, source=1, psn=psn,
                         payload_bytes=32, sack_base=base, sack_status=status)
        expected.append(ethernet_frame(sack, bitmap.to_bytes(32, "little"), outgoing=True))
        if status == 0:
            mem_data.extend(fragment)
            mem_addresses.extend(0x2000 + offset + i for i in range(len(fragment)))
    header = x5_header(1, psn=3, token=0xaa, count=1, payload_bytes=1,
                       address=0x2000, rkey=0x01020305)
    incoming.append(ethernet_frame(header, b"\x99"))
    events.append(event(6, 1, 0xaa, 3))
    good_header = x5_header(1, psn=3, token=0xaa, count=1, payload_bytes=1,
                            address=0x2000, rkey=0x01020304)
    bad_crc = bytearray(ethernet_frame(good_header, b"\x99"))
    bad_crc[-1] ^= 0x80
    incoming.append(bytes(bad_crc))
    events.append(event(4))
    bad_checksum = bytearray(ethernet_frame(good_header, b"\x99"))
    bad_checksum[24] ^= 1
    incoming.append(bytes(bad_checksum))
    events.append(event(4))
    bad_reserved = bytearray(good_header)
    bad_reserved[11] = 1
    incoming.append(ethernet_frame(bytes(bad_reserved), b"\x99"))
    events.append(event(3))
    wrong_qpn = bytearray(good_header)
    wrong_qpn[18] = 3
    incoming.append(ethernet_frame(bytes(wrong_qpn), b"\x99"))
    events.append(event(5))
    overflow = x5_header(1, psn=3, token=0xaa, count=2, payload_bytes=2,
                         address=0xffffffffffffffff, rkey=0x01020304)
    incoming.append(ethernet_frame(overflow, b"\x99\x88"))
    events.append(event(6, 1, 0xaa, 3))
    peer_bitmap = (1 << 255) | (1 << 19) | 2
    peer_header = x5_header(4, psn=99, payload_bytes=32, sack_base=72, sack_status=2)
    incoming.append(ethernet_frame(peer_header, peer_bitmap.to_bytes(32, "little")))
    events.append(event(0, 4, 0, 99))
    for name, frames in [("stimulus", incoming), ("expected", expected)]:
        data = b"".join(frame + bytes(512 - len(frame)) for frame in frames)
        (output / (name + ".hex")).write_text(
            "\n".join(f"{v:02x}" for v in data + bytes(65536 - len(data))) + "\n")
    for name, frames in [("rx", incoming), ("tx", expected)]:
        (output / (name + "-lengths.hex")).write_text(
            "\n".join(f"{v:08x}" for v in
                      [len(frame) for frame in frames] + [0] * (128 - len(frames))) + "\n")
    (output / "events.hex").write_text(
        "\n".join(f"{value:018x}" for value in events + [0] * (128 - len(events))) + "\n")
    (output / "memory.hex").write_text(
        "\n".join(f"{value:02x}" for value in mem_data + bytes(1024 - len(mem_data))) + "\n")
    (output / "addresses.hex").write_text(
        "\n".join(f"{value:016x}" for value in mem_addresses + [0] * (1024 - len(mem_addresses))) + "\n")


def fixtures(output, count=129, k=3, format=1):
    weights = [0x3f80, 0x3f00, 0xbf80]
    activation = bytes(i & 255 for i in range(count << format))
    outputs = [[(0x3e00 + ((j * 17 + e * 31) & 255)) ^ (0x8000 if (j + e) % 5 == 0 else 0)
                for j in range(count)] for e in range(k)]
    if format == 0:
        outputs = [[v & 255 for v in values] for values in outputs]
    expected = []
    fragments = (len(activation) + 255) // 256
    for rank in range(k):
        for offset in range(0, len(activation), 256):
            payload = activation[offset:offset + 256]
            header = x5_header(2, destination=2, source=1,
                               psn=len(expected), token=0x12340055,
                               expert=rank, rank=rank, k=k, count=count,
                               offset=offset >> format, payload_bytes=len(payload),
                               format=format, final=offset + len(payload) == len(activation),
                               weight=weights[rank])
            expected.append(ethernet_frame(header, payload, outgoing=True))
    incoming = []
    received = set()
    base = 0
    for psn in reversed(range(k * fragments)):
        rank, fragment = divmod(psn, fragments)
        offset = fragment * 256
        payload = b"".join(v.to_bytes(1 << format, "little")
                           for v in outputs[rank])[offset:offset + 256]
        header = x5_header(3, psn=psn, token=0x12340055,
                           expert=rank, rank=rank, k=k, count=count,
                           offset=offset >> format, payload_bytes=len(payload),
                           format=format, final=offset + len(payload) == len(activation),
                           weight=weights[rank])
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
    combined = b"".join(combine(weights[:k], [outputs[r][j] for r in range(k)],
                                fp8=format == 0).to_bytes(2, "little")
                        for j in range(count))
    (output / "combined.hex").write_text(
        "\n".join(f"{v:02x}" for v in combined + bytes(1024 - len(combined))) + "\n")


def main():
    root = Path(__file__).resolve().parents[1]
    start = datetime.datetime.now(datetime.timezone.utc)
    case = sys.argv[1] if len(sys.argv) > 1 else "moe"
    if case not in {"moe", "write"}:
        raise ValueError(f"unknown integration case {case}")
    output = root / "evidence/preparation" / (
        "verifier-integration-" + case + "-" + start.strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    relative = lambda p: str(p.relative_to(root))
    sources = [p for pattern in ("rtl/*.sv", "tests/*", "design/*.md")
               for p in sorted(root.glob(pattern)) if p.is_file()]
    receipt = {"kind": "verifier-top-integration-preparation",
               "argv": [sys.executable, "tests/prepare_integration.py", *sys.argv[1:]],
               "cwd": ".", "start_utc": start.isoformat(), "commands": [],
               "source_sha256": {relative(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sources}}
    for p in sources:
        copy = output / "sources" / p.relative_to(root)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(p.read_bytes())
    exit_code = 1
    try:
        (fixtures if case == "moe" else write_fixtures)(output)
        commands = [["iverilog", "-V"], ["vvp", "-V"]]
        for width in (64, 512):
            tb = output / f"top-{width}.sv"
            tb.write_text(top_testbench(root, width,
                                      "integration_body.svh" if case == "moe" else "write_body.svh"))
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
