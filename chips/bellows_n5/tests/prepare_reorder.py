"""Independent set-valued modular receive-window reference and retained probe."""

import datetime
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time


def vectors(qps, seed):
    bases = [0] * qps
    enabled = [False] * qps
    received = [set() for _ in range(qps)]

    def configure(qp, base, enable=True):
        bases[qp] = base
        enabled[qp] = enable
        received[qp].clear()
        return f"0 {qp} {base:06x} {int(enable)} 0 0 0 0\n"

    def request(qp, psn, commit=True):
        psn &= 0xffffff
        distance = (psn - bases[qp]) & 0xffffff
        if not enabled[qp]:
            status = 3
        elif distance >= 1 << 23 or psn in received[qp]:
            status = 1
        elif distance >= 256:
            status = 2
        else:
            status = 0
        retired = 0
        if status == 0 and commit:
            received[qp].add(psn)
            while bases[qp] in received[qp]:
                received[qp].remove(bases[qp])
                bases[qp] = (bases[qp] + 1) & 0xffffff
                retired += 1
        bitmap = sum(1 << ((value - bases[qp]) & 0xffffff)
                     for value in received[qp])
        delay = 257 + retired if status == 0 and commit else 256
        return (f"1 {qp} {psn:06x} {int(commit)} {status} "
                f"{bases[qp]:06x} {bitmap:064x} {delay}\n")

    lines = []
    for qp in range(qps):
        lines.append(configure(qp, (0xffff80 + qp * 31) & 0xffffff))
    rng = random.Random(seed)
    # Full reachable occupancy: every nonzero offset, then close the base gap.
    for block in range(4):
        qp = block % qps
        base = bases[qp]
        offsets = list(range(1, 256))
        if block:
            rng.shuffle(offsets)
        for offset in offsets:
            lines.append(request(qp, base + offset))
        lines.append(request(qp, base))
    for replay in range(256):
        qp = replay % qps
        lines.append(request(qp, bases[qp] - 1))
    for qp in range(qps):
        lines.append(request(qp, bases[qp] + 256))
        lines.append(request(qp, bases[qp] + (1 << 23) - 1))
        lines.append(request(qp, bases[qp] + (1 << 23)))
    lines.append(request(0, bases[0] + 100, commit=False))
    lines.append(request(0, bases[0] + 100))
    lines.append(configure(0, 0x123456))
    lines.append(request(0, 0x123456, commit=False))
    lines.append(configure(0, 0x654321, enable=False))
    lines.append(request(0, 0x654321))
    return "".join(lines)


def main():
    root = Path(__file__).resolve().parents[1]
    start = datetime.datetime.now(datetime.timezone.utc)
    output = root / "evidence/preparation" / (
        "verifier-reorder-" + start.strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    relative = lambda p: str(p.relative_to(root))
    sources = [p for pattern in ("rtl/*.sv", "tests/*", "design/*.md")
               for p in sorted(root.glob(pattern)) if p.is_file()]
    receipt = {"kind": "verifier-reorder-preparation",
               "argv": [sys.executable, "tests/prepare_reorder.py"],
               "cwd": ".", "start_utc": start.isoformat(), "commands": [],
               "source_sha256": {relative(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sources}}
    if len(sys.argv) > 1:
        receipt["repair_of"] = sys.argv[1]
    for p in sources:
        target = output / "sources" / p.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    exit_code = 1
    try:
        commands = [["iverilog", "-V"], ["vvp", "-V"]]
        for qps in (1, 3, 8):
            executable = output / f"reorder-{qps}.vvp"
            commands.append(["iverilog", "-g2012", "-Wall", "-s", "reorder_tb",
                             f"-Preorder_tb.QPS={qps}", "-o", relative(executable),
                             "tests/reorder_tb.sv", "rtl/bellows_n5_reorder.sv"])
            for seed in (17, 89, 203):
                stimulus = output / f"vectors-{qps}-{seed}.txt"
                stimulus.write_text(vectors(qps, seed))
                commands.append(["vvp", relative(executable),
                                 "+vectors=" + relative(stimulus)])
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
