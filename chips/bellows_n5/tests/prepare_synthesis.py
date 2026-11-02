"""Source-bound advisory coarse-synthesis probe with complete netlist retention."""

import datetime
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    start = datetime.datetime.now(datetime.timezone.utc)
    output = root / "evidence/preparation" / (
        "verifier-synthesis-" + start.strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    relative = lambda p: str(p.relative_to(root))
    sources = [p for pattern in ("rtl/*.sv", "tests/*", "design/*.md")
               for p in sorted(root.glob(pattern)) if p.is_file()]
    receipt = {"kind": "verifier-coarse-synthesis-preparation",
               "argv": [sys.executable, "tests/prepare_synthesis.py"],
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
        netlist = output / "tiny64.json"
        script = output / "tiny64.ys"
        script.write_text(
            "read_verilog -sv " + " ".join(relative(p) for p in root.glob("rtl/*.sv")) +
            "\nhierarchy -check -top bellows_n5_top "
            "-chparam DATA_WIDTH 64 -chparam MAX_PACKET_BYTES 1 "
            "-chparam MAX_SG 1 -chparam QPS 1 -chparam EXPERTS 1 "
            "-chparam MAX_K 1 -chparam TOKENS 1 -chparam MAX_TOKEN_ELEMS 1\n"
            "proc\nopt_expr\nopt_clean\ncheck -assert\nfsm\nopt\nwreduce\n"
            "memory_dff\nmemory_collect\nopt_clean\ncheck -assert\n"
            "stat\nwrite_json " + relative(netlist) + "\n")
        for index, command in enumerate([["yosys", "-V"],
                                         ["yosys", "-Q", "-T", "-s", relative(script)]]):
            entry = {"argv": command, "cwd": ".", "timeout_s": 3600,
                     "start_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     "stdout": relative(output / f"command-{index}.stdout.txt"),
                     "stderr": relative(output / f"command-{index}.stderr.txt")}
            receipt["commands"].append(entry)
            before = time.monotonic()
            with (root / entry["stdout"]).open("wb") as stdout, (
                    root / entry["stderr"]).open("wb") as stderr:
                try:
                    result = subprocess.run(command, cwd=root, stdout=stdout,
                                            stderr=stderr, timeout=3600, check=False)
                    entry.update(exit_code=result.returncode, timed_out=False)
                except subprocess.TimeoutExpired:
                    entry.update(exit_code=None, timed_out=True)
            entry.update(end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         duration_s=time.monotonic() - before)
            if entry["timed_out"] or entry["exit_code"] != 0:
                raise RuntimeError(f"command {index} failed")
        document = json.loads(netlist.read_text())
        counts = {}
        for module in document["modules"].values():
            for cell in module["cells"].values():
                counts[cell["type"]] = counts.get(cell["type"], 0) + 1
        forbidden = {name: count for name, count in counts.items()
                     if name in {"$div", "$mod", "$divfloor", "$modfloor"}
                     or ("latch" in name.lower() and name not in document["modules"])}
        receipt["cell_types"] = counts
        if forbidden:
            raise RuntimeError(f"forbidden synthesized operators: {forbidden}")
        compressed = netlist.with_suffix(".json.gz")
        original_size = 0
        original_hash = hashlib.sha256()
        with netlist.open("rb") as source, gzip.open(compressed, "wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                original_size += len(chunk)
                original_hash.update(chunk)
                target.write(chunk)
        checked_hash = hashlib.sha256()
        checked_size = 0
        with gzip.open(compressed, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                checked_hash.update(chunk)
                checked_size += len(chunk)
        if checked_size != original_size or checked_hash.digest() != original_hash.digest():
            raise RuntimeError("lossless netlist retention comparison failed")
        receipt["netlist"] = {"path": relative(compressed),
                              "decompressed_bytes": original_size,
                              "sha256": original_hash.hexdigest(),
                              "round_trip_compared": True}
        netlist.unlink()
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
