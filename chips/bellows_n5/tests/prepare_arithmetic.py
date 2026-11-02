"""Bounded advisory public-pin arithmetic probe; not an L1 acceptance runner."""

import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import arithmetic_vectors, bf16_add, bf16_mul, reflected_crc


def main():
    root = Path(__file__).resolve().parents[1]
    start = datetime.datetime.now(datetime.timezone.utc)
    output = root / "evidence/preparation" / (
        "verifier-arithmetic-" + start.strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    relative = lambda p: str(p.relative_to(root))
    sources = sorted(root.glob("rtl/*.sv")) + sorted(root.glob("tests/*"))
    sources = [p for p in sources if p.is_file()]
    receipt = {
        "kind": "verifier-arithmetic-preparation",
        "argv": [sys.executable, "tests/prepare_arithmetic.py"],
        "cwd": ".", "start_utc": start.isoformat(),
        "source_sha256": {relative(p): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sources},
        "commands": [],
    }
    for source in sources:
        target = output / "sources" / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    exit_code = 1
    try:
        assert reflected_crc(b"123456789", 32, 0x82f63b78) == 0xe3069283
        assert reflected_crc(b"123456789", 64, 0x9a6c9329ac4bc9b5) == 0xae8b14860a799888
        vector_path = output / "arithmetic.txt"
        count = 0
        with vector_path.open("w") as stream:
            for a, b in arithmetic_vectors():
                stream.write(f"{a:04x} {b:04x} {bf16_mul(a,b):04x} {bf16_add(a,b):04x}\n")
                count += 1
        receipt["generated_vectors"] = count
        commands = [
            ["iverilog", "-V"],
            ["vvp", "-V"],
            ["iverilog", "-g2012", "-Wall", "-s", "arithmetic_tb",
             "-o", relative(output / "arithmetic.vvp"),
             "tests/arithmetic_tb.sv", "rtl/bellows_n5_bf16_mul.sv",
             "rtl/furnace_reduce_alu.sv", "rtl/furnace_reduce_lane.sv"],
            ["vvp", relative(output / "arithmetic.vvp"),
             "+vectors=" + relative(vector_path)],
        ]
        for index, command in enumerate(commands):
            command_start = datetime.datetime.now(datetime.timezone.utc)
            entry = {"argv": command, "cwd": ".", "timeout_s": 600,
                     "start_utc": command_start.isoformat(),
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
                raise RuntimeError(f"probe command {index} failed: {entry}")
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
