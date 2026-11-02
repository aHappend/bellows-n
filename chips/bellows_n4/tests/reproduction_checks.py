"""Declared partial clean-directory reproduction; never a claim of a full rerun."""

import hashlib
import re
import shutil

from execution import inventory, relative


def run(execution):
    sources = inventory(execution.root)
    digest = hashlib.sha256(str(sorted(sources.items())).encode()).hexdigest()[:12]
    root = execution.folder / f"clean-reproduction-{digest}"
    root.mkdir(exist_ok=False)
    for name in sources:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(execution.root / name, target)
    if inventory(root) != sources:
        raise AssertionError("clean reproduction copied source mismatch")
    code, out, err = execution.run(
        "clean-directory-reproduction",
        ["python3", "tests/verify.py", "--probe", "reproduction-child"], cwd=root)
    if code:
        raise AssertionError(f"clean reproduction exit {code}: {out[-3000:]} {err[-1000:]}")
    matches = re.findall(r"receipt: ([^\s]+/receipt\.json)", out)
    if len(matches) != 1 or not (root / matches[0]).is_file():
        raise AssertionError("clean reproduction child receipt missing or ambiguous")
    return {"scope": "partial: compact integrated behavior and structural synthesis",
            "copied_sha256": sources,
            "receipt": relative(root / matches[0], execution.root)}
