from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .judges import Judge, exact


@dataclass(frozen=True)
class Task:
    tid: str
    prompt: str
    expected: str
    judge: Judge = exact


@dataclass
class TaskResult:
    tid: str
    ok: bool
    actual: str
    expected: str


class Harness:
    """Run a callable against a frozen task list. No YAML, no network."""

    def __init__(self, tasks: Sequence[Task]) -> None:
        if not tasks:
            raise ValueError("need at least one task")
        self.tasks = list(tasks)

    def run(self, fn: Callable[[str], str]) -> list[TaskResult]:
        out: list[TaskResult] = []
        for task in self.tasks:
            actual = fn(task.prompt)
            out.append(TaskResult(tid=task.tid, ok=task.judge(task.expected, actual), actual=actual, expected=task.expected))
        return out

    def report(self, results: Sequence[TaskResult]) -> str:
        passed = sum(1 for r in results if r.ok)
        lines = [f"# eval-harness", f"", f"Passed {passed}/{len(results)}", ""]
        for r in results:
            mark = "PASS" if r.ok else "FAIL"
            lines.append(f"- `{r.tid}` **{mark}**")
            if not r.ok:
                lines.append(f"  - expected: {r.expected!r}")
                lines.append(f"  - actual: {r.actual!r}")
        return "\n".join(lines) + "\n"

    def score(self, results: Sequence[TaskResult]) -> float:
        if not results:
            return 0.0
        return sum(1 for r in results if r.ok) / len(results)
