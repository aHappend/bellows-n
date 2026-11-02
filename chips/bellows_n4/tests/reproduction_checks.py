"""Declared partial clean-directory reproduction; never a claim of a full rerun."""

import hashlib
import os
import shutil

from execution import Execution, fresh, inventory, relative
import integrated_checks
import structural_checks


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
    folder = fresh("partial-reproduction", root=root)
    clean = Execution(folder, root=root)
    clean.deadline = min(clean.deadline, execution.deadline)
    previous_cwd = os.getcwd()
    try:
        os.chdir(root)
        coverage = {
            "integrated": integrated_checks.run(clean, width=64, compact=True,
                                                boundary=(128, 1, 1)),
            "structural": structural_checks.run(clean, compact=True),
        }
    except (AssertionError, RuntimeError, FileNotFoundError) as error:
        receipt = clean.finish("failed", str(error))
        raise AssertionError(f"clean reproduction failed: {error}; "
                             f"{relative(root / receipt, execution.root)}") from error
    finally:
        os.chdir(previous_cwd)
    receipt = clean.finish("passed", "partial representative behavior and structural synthesis",
                           **coverage)
    return {"scope": "partial: compact integrated behavior and structural synthesis",
            "copied_sha256": sources,
            "receipt": relative(root / receipt, execution.root)}
