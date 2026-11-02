"""Source-bound execution and immutable project-relative diagnostic receipts."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parent.parent


def utc():
    return datetime.now(timezone.utc).isoformat()


def relative(path, root=ROOT):
    return Path(path).resolve().relative_to(root.resolve()).as_posix()


def inventory(root=ROOT):
    paths = []
    for pattern in ("rtl/*.sv", "tests/*.py", "design/SPEC.md",
                    "design/ARCHITECTURE.md", "furnace_x3_reference/rtl/*.sv"):
        paths.extend(root.glob(pattern))
    return {relative(p, root): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))}


def fresh(stem, *, preparation=False, root=ROOT):
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parent = root / "evidence"
    if preparation:
        parent /= "preparation"
    path = parent / f"{stem}-{suffix}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class Execution:
    def __init__(self, folder, root=ROOT):
        self.folder = Path(folder)
        self.root = Path(root)
        self.hashes = inventory(self.root)
        self.records = []
        self.started = utc()
        self.invocation = ["python3", relative(Path(sys.argv[0]), ROOT), *sys.argv[1:]]
        self.deadline = time.monotonic() + 2700
        inherited = os.environ.get("FURNACE_CHECK_DEADLINE")
        if inherited is not None:
            self.deadline = min(self.deadline, float(inherited))
        self.timed_out = False

    def run(self, label, argv, *, version_tool=None, cwd=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.timed_out = True
            raise RuntimeError("complete L1 execution exceeded its 2700-second budget")
        budget = min(600, remaining)
        deadline = time.monotonic() + budget
        cwd = Path(cwd) if cwd is not None else self.root
        command_dir = self.folder / label
        command_dir.mkdir(exist_ok=False)
        start = utc()
        stdout = command_dir / "stdout.txt"
        stderr = command_dir / "stderr.txt"
        tool = shutil.which(argv[0])
        if tool is None:
            raise FileNotFoundError(f"required tool missing: {argv[0]}")
        version_tool = version_tool or argv[0]
        version_args = [version_tool, "-V" if version_tool in ("iverilog", "vvp", "yosys")
                        else "--version"]
        timed_out = False
        version_exit = None
        exit_code = None
        try:
            version_exit = self._execute(
                version_args, command_dir / "tool-version.stdout.txt",
                command_dir / "tool-version.stderr.txt", deadline, label + "-version", cwd)
            exit_code = self._execute(argv, stdout, stderr, deadline, label, cwd)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.timed_out = True
        record = {
            "argv": argv, "cwd": relative(cwd, self.root), "start": start, "end": utc(),
            "source_sha256": self.hashes, "timeout_s": budget,
            "timed_out": timed_out, "exit_code": exit_code,
            "process_scope_settled": True,
            "stdout": relative(stdout, self.root),
            "stderr": relative(stderr, self.root),
            "tool_version_argv": version_args,
            "tool_version_exit": version_exit,
            "tool_version_stdout": relative(command_dir / "tool-version.stdout.txt", self.root),
            "tool_version_stderr": relative(command_dir / "tool-version.stderr.txt", self.root),
        }
        receipt = command_dir / "receipt.json"
        receipt.write_text(json.dumps(record, indent=2) + "\n")
        self.records.append(relative(receipt, self.root))
        if timed_out:
            raise RuntimeError(f"{label} exceeded its {budget:.1f}-second execution budget; "
                               f"retained {relative(receipt, self.root)}")
        return exit_code, stdout.read_text(), stderr.read_text()

    def _execute(self, argv, stdout, stderr, deadline, label, cwd):
        with stdout.open("w") as out, stderr.open("w") as err:
            environment = os.environ.copy()
            environment["FURNACE_CHECK_DEADLINE"] = str(deadline - 10)
            child = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=err,
                                     start_new_session=True, env=environment)
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(argv, 0)
                    try:
                        return child.wait(timeout=min(30, remaining))
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            raise
                        print(f"PROGRESS {label}: child running; "
                              f"stdout={stdout.stat().st_size} "
                              f"stderr={stderr.stat().st_size} bytes", flush=True)
            finally:
                # This session contains only subprocesses launched by this command.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def finish(self, outcome, detail, **coverage):
        # Children have settled before their disposable compiler objects are removed.
        for directory in self.folder.rglob("*-obj"):
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file() and path.suffix in (".o", ".a", ".gch", ".d"):
                        path.unlink()
        receipt = {
            "argv": self.invocation,
            "cwd": ".", "start": self.started, "end": utc(),
            "source_root": relative(self.root, ROOT),
            "timeout_s": 2700, "timed_out": self.timed_out,
            "exit_code": 0 if outcome == "passed" else 1,
            "source_sha256": self.hashes, "commands": self.records,
            "outcome": outcome, "detail": detail, "coverage": coverage,
            "generated_sha256": {
                relative(path, self.root): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.folder.rglob("*"))
                if path.is_file() and (path.suffix in (".sv", ".hex", ".json", ".ys")
                                       or path.name == "commands.txt")
            },
        }
        (self.folder / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return relative(self.folder / "receipt.json", self.root)
