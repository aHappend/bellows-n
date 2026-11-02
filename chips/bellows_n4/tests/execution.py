"""Source-bound execution and immutable project-relative diagnostic receipts."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
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

    def run(self, label, argv, *, version_tool=None):
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
        version = subprocess.run(version_args, cwd=self.root, capture_output=True,
                                 text=True, check=False)
        (command_dir / "tool-version.stdout.txt").write_text(version.stdout)
        (command_dir / "tool-version.stderr.txt").write_text(version.stderr)
        with stdout.open("w") as out, stderr.open("w") as err:
            child = subprocess.Popen(argv, cwd=self.root, stdout=out, stderr=err)
            while True:
                try:
                    child.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    print(f"PROGRESS {label}: child running; "
                          f"stdout={stdout.stat().st_size} stderr={stderr.stat().st_size} bytes",
                          flush=True)
        record = {
            "argv": argv, "cwd": ".", "start": start, "end": utc(),
            "source_sha256": self.hashes, "timeout_s": None,
            "timed_out": False, "exit_code": child.returncode,
            "stdout": relative(stdout, self.root),
            "stderr": relative(stderr, self.root),
            "tool_version_argv": version_args,
            "tool_version_exit": version.returncode,
            "tool_version_stdout": relative(command_dir / "tool-version.stdout.txt", self.root),
            "tool_version_stderr": relative(command_dir / "tool-version.stderr.txt", self.root),
        }
        receipt = command_dir / "receipt.json"
        receipt.write_text(json.dumps(record, indent=2) + "\n")
        self.records.append(relative(receipt, self.root))
        return child.returncode, stdout.read_text(), stderr.read_text()

    def finish(self, outcome, detail, **coverage):
        # Children have settled before their disposable compiler objects are removed.
        for directory in self.folder.rglob("*-obj"):
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file() and path.suffix in (".o", ".a", ".gch", ".d"):
                        path.unlink()
        receipt = {
            "argv": ["python3", relative(Path(sys.argv[0]), self.root), *sys.argv[1:]],
            "cwd": ".", "start": self.started, "end": utc(),
            "timeout_s": None, "timed_out": False,
            "exit_code": 0 if outcome == "passed" else 1,
            "source_sha256": self.hashes, "commands": self.records,
            "outcome": outcome, "detail": detail, "coverage": coverage,
            "generated_sha256": {
                relative(path, self.root): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.folder.rglob("*"))
                if path.is_file() and path.suffix in (".sv", ".hex", ".json")
            },
        }
        (self.folder / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return relative(self.folder / "receipt.json", self.root)
