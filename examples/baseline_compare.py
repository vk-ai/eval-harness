"""Fail only on regressions vs a saved baseline (not on known failures)."""

import tempfile
from pathlib import Path

from eval_harness import Harness, Task, contains

h = Harness([
    Task("kenya", "Capital of Kenya?", "Nairobi", contains),
    Task("math", "12*12", "144"),
    Task("hard", "Riemann hypothesis?", "proof"),  # known failure
])

def main_branch(p: str) -> str:
    return "Nairobi" if "Kenya" in p else "144" if "12" in p else "no idea"

def pr_branch(p: str) -> str:
    return "Nairobi" if "Kenya" in p else "143" if "12" in p else "no idea"  # broke math

with tempfile.TemporaryDirectory() as d:
    baseline = Path(d) / "baseline.json"
    h.save(h.run(main_branch), str(baseline))           # on main
    cmp = h.compare(h.run(pr_branch), str(baseline))    # on the PR
    print(cmp.report())
    print("exit code:", cmp.exit_code)
