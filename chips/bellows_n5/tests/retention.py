"""Exclusive source-bound experiment records, shared by L1 and preparation."""

import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(root):
    return sorted(p for pattern in ("rtl/*.sv", "design/*.md", "tests/*",
                                    "furnace_x4_reference/rtl/*.sv")
                  for p in root.glob(pattern) if p.is_file())


class Run:
    def __init__(self, root, prefix, argv):
        self.root = root.resolve()
        prefix = Path(prefix)
        if prefix.is_absolute() or ".." in prefix.parts or prefix.parts[0] != "evidence":
            raise ValueError("output prefix must be project-relative under evidence/")
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.output = self.root / (str(prefix) + "-" + stamp)
        self.output.mkdir(parents=True, exist_ok=False)
        self.receipt = {"argv": argv, "cwd": ".", "start_utc": utc(),
                        "commands": [], "source_sha256": {}}
        self.summary = {"comparisons": {}, "runs": []}
        for path in sources(self.root):
            relative = path.relative_to(self.root)
            self.receipt["source_sha256"][str(relative)] = digest(path)
            copy = self.output / "sources" / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(path.read_bytes())

    def relative(self, path):
        return str(Path(path).resolve().relative_to(self.root))

    def command(self, argv, *, cwd=None, timeout=3600, allowed=(0,), env=None):
        index = len(self.receipt["commands"])
        entry = {"argv": [str(v) for v in argv],
                 "cwd": self.relative(cwd or self.root), "timeout_s": timeout,
                 "start_utc": utc(), "stdout": f"command-{index}.stdout.txt",
                 "stderr": f"command-{index}.stderr.txt"}
        self.receipt["commands"].append(entry)
        before = time.monotonic()
        with (self.output / entry["stdout"]).open("xb") as stdout, (
                self.output / entry["stderr"]).open("xb") as stderr:
            process = subprocess.Popen(entry["argv"], cwd=cwd or self.root,
                                       stdout=stdout, stderr=stderr, env=env)
            try:
                while True:
                    try:
                        code = process.wait(timeout=min(30, max(
                            0.01, timeout - (time.monotonic() - before))))
                        entry.update(exit_code=code, timed_out=False)
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() - before >= timeout:
                            process.kill()
                            process.wait()
                            entry.update(exit_code=process.returncode, timed_out=True)
                            break
                        print(f"tool execution active: command {index}, "
                              f"{int(time.monotonic() - before)}s", flush=True)
            finally:
                entry.update(end_utc=utc(), duration_s=time.monotonic() - before)
        if entry["timed_out"] or entry["exit_code"] not in allowed:
            raise RuntimeError(f"tool execution failed: command {index}, "
                               f"exit={entry['exit_code']}, timeout={entry['timed_out']}; "
                               f"see {self.relative(self.output)}/{entry['stderr']}")
        return entry, (self.output / entry["stdout"]).read_text(errors="replace")

    def compress(self, path):
        path = Path(path)
        size, sha = path.stat().st_size, digest(path)
        compressed = path.with_suffix(path.suffix + ".gz")
        with path.open("rb") as source, compressed.open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
        checked_hash, checked_size = hashlib.sha256(), 0
        with gzip.open(compressed, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checked_hash.update(chunk)
                checked_size += len(chunk)
        if checked_size != size or checked_hash.hexdigest() != sha:
            raise RuntimeError("lossless artifact round-trip mismatch")
        self.receipt.setdefault("compressed_artifacts", []).append({
            "path": str(compressed.relative_to(self.output)),
            "decompressed_bytes": size, "decompressed_sha256": sha,
            "compressed_sha256": digest(compressed), "round_trip_compared": True})
        path.unlink()
        return compressed

    def finish(self, error=None):
        self.receipt.update(end_utc=utc(), exit_code=int(error is not None))
        self.summary["status"] = "failed" if error is not None else "passed"
        if error is not None:
            self.receipt["error"] = self.summary["error"] = str(error)
        (self.output / "summary.json").write_text(json.dumps(self.summary, indent=2) + "\n")
        (self.output / "receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
        archive = self.output / "artifacts.tar.gz"
        with tarfile.open(archive, "x:gz") as bundle:
            for path in sorted(self.output.iterdir()):
                if path != archive:
                    bundle.add(path, arcname=path.name)
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                if member.isfile():
                    extracted = bundle.extractfile(member)
                    original = self.output / member.name
                    if hashlib.sha256(extracted.read()).hexdigest() != digest(original):
                        raise RuntimeError(f"archive round-trip mismatch: {member.name}")
        print(json.dumps({"receipt": self.relative(self.output / "receipt.json"),
                          "status": self.summary["status"]}), flush=True)
